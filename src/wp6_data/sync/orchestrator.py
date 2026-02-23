"""Main sync orchestration logic."""

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from tenacity import RetryError

from wp6_data.api import SensorReading, SpoHFClient
from wp6_data.config import Settings
from wp6_data.graph import CONSTRAINTS, Neo4jConnection, batch_upsert_readings
from wp6_data.sync.state import SyncStateManager


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt

logger = structlog.get_logger()

BATCH_SIZE = 1000  # Records per Neo4j transaction


def _log_window_summary(
    window_start: datetime,
    window_records: int,
    total_records: int,
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
        total_records=total_records,
        sensors=sensors,
    )


class SyncOrchestrator:
    """Orchestrate sensor data sync from SPoHF API to Neo4j."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = SpoHFClient(
            settings.api_base_url,
            settings.api_token,
            settings.sync_page_size,
        )
        self.neo4j = Neo4jConnection(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            settings.neo4j_database,
        )

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

        try:
            await self.neo4j.connect()
            await self.neo4j.ensure_schema(CONSTRAINTS)

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
            await self.neo4j.close()

        return stats

    async def _sync_endpoint(self, endpoint: str) -> int:
        """Sync a single API endpoint.

        Uses windowed fetching to get all historical data when doing initial sync,
        or regular pagination for incremental syncs.

        Returns:
            Number of records synced
        """
        start_time = datetime.now(UTC)
        async with self.neo4j.session() as session:
            state = SyncStateManager(session, endpoint)
            since, is_initial = await state.get_last_timestamp_with_status(
                self.settings.sync_lookback_hours
            )

            # Determine sync mode: auto (based on state), windowed, or incremental
            sync_mode = self.settings.sync_mode.lower()
            if sync_mode == "windowed":
                use_windowed = True
            elif sync_mode == "incremental":
                use_windowed = False
            else:  # auto
                use_windowed = is_initial

            logger.info(
                "sync_starting",
                endpoint=endpoint,
                since=since.isoformat(),
                mode="windowed" if use_windowed else "incremental",
                forced=sync_mode != "auto",
            )

            batch: list[dict[str, Any]] = []
            latest_timestamp = since
            total_count = 0

            # Per-sensor stats for windowed summary
            sensor_stats: dict[str, dict] = defaultdict(
                lambda: {"count": 0, "min": None, "max": None}
            )

            def on_window_complete(window_start: datetime, window_records: int, total: int):
                _log_window_summary(window_start, window_records, total, sensor_stats)

            # Use windowed fetch for full historical sync, regular for incremental
            if use_windowed:
                fetch_iter = self.client.fetch_all_windowed(
                    endpoint,
                    since,
                    max_windows=self.settings.sync_max_windows,
                    window_days=self.settings.sync_window_days,
                    on_window_complete=on_window_complete,
                )
            else:
                fetch_iter = self.client.fetch_all_since(
                    endpoint,
                    since,
                    self.settings.sync_max_pages,
                )

            try:
                async for reading in fetch_iter:
                    batch.append(self._reading_to_params(reading))

                    # Track per-sensor stats
                    tag = reading.sensor_tag
                    dt = reading.datetime_measure.isoformat()
                    s = sensor_stats[tag]
                    s["count"] += 1
                    if s["min"] is None or dt < s["min"]:
                        s["min"] = dt
                    if s["max"] is None or dt > s["max"]:
                        s["max"] = dt

                    # Track the latest timestamp we've seen
                    reading_ts = ensure_utc(reading.timestamp)
                    if reading_ts > latest_timestamp:
                        latest_timestamp = reading_ts

                    # Flush batch when full
                    if len(batch) >= BATCH_SIZE:
                        await batch_upsert_readings(session, batch)
                        total_count += len(batch)
                        logger.debug("batch_flushed", count=len(batch), total=total_count)
                        batch = []

                # Flush remaining records
                if batch:
                    await batch_upsert_readings(session, batch)
                    total_count += len(batch)

                # Update sync state if we processed any records
                if total_count > 0:
                    await state.update_timestamp(latest_timestamp, total_count)

                # Record successful run
                duration = (datetime.now(UTC) - start_time).total_seconds()
                await state.record_run_result(
                    success=True,
                    duration_seconds=duration,
                    record_count=total_count,
                )

                logger.info(
                    "endpoint_synced",
                    endpoint=endpoint,
                    records=total_count,
                    latest=latest_timestamp.isoformat(),
                )
                return total_count

            except (httpx.HTTPStatusError, RetryError) as e:
                # Extract API error details
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
            # Extract just the status message for the error field
            match = re.search(r"(\d{3}\s+\w+[\w\s]*)", str(exc))
            msg = match.group(1) if match else str(exc)[:200]
            return status, detail, msg

        return None, None, str(exc)[:200]

    def _reading_to_params(self, reading: SensorReading) -> dict[str, Any]:
        """Convert SensorReading to Neo4j query parameters."""
        return {
            "sensor_id": reading.sensor_id,
            "project": reading.project,
            "device_name": reading.device_name,
            "sensor_tag": reading.sensor_tag,
            "value": reading.value,
            "datetime_measure": reading.datetime_measure.isoformat(),
            "api_timestamp": reading.timestamp.isoformat(),
        }
