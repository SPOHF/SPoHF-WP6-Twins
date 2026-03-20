"""Main sync orchestration logic."""

import re
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from tenacity import RetryError

from wp6_data.api import SensorReading, SpoHFClient
from wp6_data.config import Settings
from wp6_data.db import (
    close_pool,
    ensure_schema,
    get_pool,
    init_pool,
    upsert_daily_coverage,
    upsert_readings,
)
from wp6_data.sync.state import SyncStateManager


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt

logger = structlog.get_logger()

BATCH_SIZE = 1000  # Records per transaction
FULL_SYNC_START = datetime(2024, 1, 1, tzinfo=UTC)
INCREMENTAL_LOOKBACK_DAYS = 30
CONSECUTIVE_DUPE_WINDOW_THRESHOLD = 3


def _log_window_summary(
    window_start: datetime,
    window_records: int,
    total_records: int,
    total_created: int,
    total_duplicates: int,
    sensor_stats: dict[str, dict],
) -> None:
    """Log a running summary after each sync window."""
    sensors = {
        tag: {
            "count": s["count"],
            "min_date": s["min"][:19] if s["min"] else None,
            "max_date": s["max"][:19] if s["max"] else None,
        }
        for tag, s in sorted(sensor_stats.items())
    }
    logger.info(
        "window_summary",
        window=window_start.strftime("%Y-%m-%d"),
        window_records=window_records,
        total_fetched=total_records,
        total_created=total_created,
        total_duplicates=total_duplicates,
        sensors=sensors,
    )


def _generate_windows(
    mode: str, window_days: int
) -> Iterator[tuple[datetime, datetime]]:
    """Generate (window_start, window_end) tuples, backwards from now.

    Full mode: from now+1d back to 2024-01-01.
    Incremental mode: from now+1d back by INCREMENTAL_LOOKBACK_DAYS.
    """
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    start = FULL_SYNC_START if mode == "full" else end - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)

    window_end = end
    while window_end > start:
        window_start = max(window_end - timedelta(days=window_days), start)
        yield window_start, window_end
        window_end = window_start


class SyncOrchestrator:
    """Orchestrate sensor data sync from SPoHF API to TimescaleDB."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = SpoHFClient(
            settings.api_base_url,
            settings.api_token,
            settings.sync_page_size,
        )
        self._dsn = settings.tsdb_url

    async def run(self) -> dict[str, Any]:
        """Execute full sync cycle.

        Returns:
            Stats dict with endpoints, total_records, errors, duration_seconds
        """
        start_time = datetime.now(UTC)
        stats: dict[str, Any] = {
            "endpoints": {},
            "total_records": 0,
            "errors": [],
        }

        pool = await init_pool(self._dsn)
        try:
            await ensure_schema(pool)

            # Sync each configured endpoint
            for endpoint in self.settings.endpoint_list:
                try:
                    count = await self._sync_endpoint(endpoint)
                    stats["endpoints"][endpoint] = count
                    stats["total_records"] += count
                except Exception as e:
                    logger.exception("endpoint_sync_failed", endpoint=endpoint)
                    stats["errors"].append(f"{endpoint}: {e}")

            stats["duration_seconds"] = (
                datetime.now(UTC) - start_time
            ).total_seconds()
            logger.info("sync_completed", **stats)

        finally:
            await close_pool()

        return stats

    @staticmethod
    def _update_sensor_stats(
        sensor_stats: dict[str, dict], tag: str, dt_iso: str
    ) -> None:
        """Update per-sensor min/max/count tracking."""
        s = sensor_stats[tag]
        s["count"] += 1
        if s["min"] is None or dt_iso < s["min"]:
            s["min"] = dt_iso
        if s["max"] is None or dt_iso > s["max"]:
            s["max"] = dt_iso

    async def _flush_batch(
        self, conn: Any, batch: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Flush a batch of readings to TimescaleDB.

        Returns:
            Tuple of (upserted, created) counts. Returns (0, 0) for empty batch.
        """
        if not batch:
            return 0, 0
        upserted, created = await upsert_readings(conn, batch)
        # Update daily_coverage for the days touched by this batch
        coverage_keys = {
            (r["device_name"], r["sensor_tag"], r["datetime_measure"][:10])
            for r in batch
        }
        coverage_records = [
            {"device_name": dn, "sensor_tag": st, "day": day}
            for dn, st, day in coverage_keys
        ]
        await upsert_daily_coverage(conn, coverage_records)
        await conn.commit()
        logger.debug("batch_flushed", upserted=upserted, created=created)
        return upserted, created

    async def _sync_endpoint(self, endpoint: str) -> int:
        """Sync a single API endpoint using time windows.

        Generates windows backwards from now. In incremental mode, stops early
        when consecutive windows contain only duplicate records.

        Returns:
            Number of records upserted
        """
        start_time = datetime.now(UTC)
        mode = self.settings.sync_mode.lower()

        pool = get_pool()

        async with pool.connection() as conn:
            state = SyncStateManager(conn, endpoint)

            logger.info(
                "sync_starting",
                endpoint=endpoint,
                mode=mode,
                window_days=self.settings.sync_window_days,
            )

            batch: list[dict[str, Any]] = []
            latest_timestamp: datetime | None = None
            total_count = 0
            total_created = 0
            consecutive_dupe_windows = 0

            sensor_stats: dict[str, dict] = defaultdict(
                lambda: {"count": 0, "min": None, "max": None}
            )

            windows = _generate_windows(mode, self.settings.sync_window_days)

            try:
                for window_start, window_end in windows:
                    window_upserted = 0
                    window_created = 0

                    async for reading in self.client.fetch_window(
                        endpoint, window_start, window_end
                    ):
                        batch.append(self._reading_to_params(reading))
                        self._update_sensor_stats(
                            sensor_stats,
                            reading.sensor_tag,
                            reading.datetime_measure.isoformat(),
                        )

                        reading_ts = ensure_utc(reading.timestamp)
                        if latest_timestamp is None or reading_ts > latest_timestamp:
                            latest_timestamp = reading_ts

                        if len(batch) >= BATCH_SIZE:
                            upserted, created = await self._flush_batch(conn, batch)
                            total_count += upserted
                            total_created += created
                            window_upserted += upserted
                            window_created += created
                            batch = []

                    # Flush remaining batch for this window
                    upserted, created = await self._flush_batch(conn, batch)
                    total_count += upserted
                    total_created += created
                    window_upserted += upserted
                    window_created += created
                    batch = []

                    _log_window_summary(
                        window_start,
                        window_upserted,
                        total_count,
                        total_created,
                        total_count - total_created,
                        sensor_stats,
                    )

                    # Incremental early-stop: if all records in window were dupes
                    if mode == "incremental" and window_upserted > 0:
                        if window_created == 0:
                            consecutive_dupe_windows += 1
                        else:
                            consecutive_dupe_windows = 0

                        if consecutive_dupe_windows >= CONSECUTIVE_DUPE_WINDOW_THRESHOLD:
                            logger.info(
                                "incremental_early_stop",
                                endpoint=endpoint,
                                consecutive_dupe_windows=consecutive_dupe_windows,
                            )
                            break

                # Update sync state if we processed any records
                if total_count > 0 and latest_timestamp is not None:
                    await state.update_timestamp(latest_timestamp, total_count)

                # Record successful run
                duration = (datetime.now(UTC) - start_time).total_seconds()
                await state.record_run_result(
                    success=True,
                    duration_seconds=duration,
                    record_count=total_count,
                )
                await conn.commit()

                logger.info(
                    "endpoint_synced",
                    endpoint=endpoint,
                    records=total_count,
                    created=total_created,
                    duplicates=total_count - total_created,
                    latest=latest_timestamp.isoformat() if latest_timestamp else None,
                )
                return total_count

            except (httpx.HTTPStatusError, RetryError) as e:
                duration = (datetime.now(UTC) - start_time).total_seconds()
                api_status, api_detail, error_msg = self._extract_api_error(e)

                await state.record_run_result(
                    success=False,
                    duration_seconds=duration,
                    record_count=total_count,
                    error=error_msg,
                    api_status=api_status,
                    api_error_detail=api_detail,
                )
                await conn.commit()
                raise

    def _extract_api_error(
        self, exc: Exception
    ) -> tuple[int | None, str | None, str]:
        """Extract API error details from exception.

        Returns:
            Tuple of (status_code, response_detail, error_message)
        """
        # Unwrap RetryError to get the underlying HTTPStatusError
        if isinstance(exc, RetryError) and exc.last_attempt.failed:
            underlying = exc.last_attempt.exception()
            if isinstance(underlying, httpx.HTTPStatusError):
                exc = underlying

        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            detail = exc.response.text[:500] if exc.response.text else None
            match = re.search(r"(\d{3}\s+\w+[\w\s]*)", str(exc))
            msg = match.group(1) if match else str(exc)[:200]
            return status, detail, msg

        return None, None, str(exc)[:200]

    def _reading_to_params(self, reading: SensorReading) -> dict[str, Any]:
        """Convert SensorReading to query parameters."""
        return {
            "sensor_id": reading.sensor_id,
            "project": reading.project,
            "device_name": reading.device_name,
            "sensor_tag": reading.sensor_tag,
            "value": reading.value,
            "datetime_measure": reading.datetime_measure.isoformat(),
            "api_timestamp": reading.timestamp.isoformat(),
        }
