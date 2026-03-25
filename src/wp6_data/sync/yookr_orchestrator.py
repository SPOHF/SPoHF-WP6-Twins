"""Yookr API → TimescaleDB sync orchestrator.

Same table format as the SPoHF sync, but fetches per-sensor from
api.yookr.org instead of all-at-once from backoffice.spohf.com.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from wp6_data.config import Settings
from wp6_data.db import (
    close_pool,
    ensure_schema,
    get_pool,
    init_pool,
    refresh_sensor_summary,
    upsert_daily_coverage,
    upsert_readings,
)
from wp6_data.sync.state import SyncStateManager
from wp6_data.yookr.client import YookrClient
from wp6_data.yookr.sensors import SensorInfo, SensorRegistry

logger = structlog.get_logger()

BATCH_SIZE = 1000
ENDPOINT_NAME = "yookr-direct"
FULL_SYNC_START = datetime(2024, 1, 1, tzinfo=UTC)
INCREMENTAL_LOOKBACK_DAYS = 7
WINDOW_DAYS = 30  # Fetch one month at a time per sensor


def _generate_monthly_windows(
    sync_from: datetime, sync_until: datetime,
) -> list[tuple[datetime, datetime]]:
    """Split a time range into ~30-day windows, oldest first."""
    windows = []
    window_start = sync_from
    while window_start < sync_until:
        window_end = min(window_start + timedelta(days=WINDOW_DAYS), sync_until)
        windows.append((window_start, window_end))
        window_start = window_end
    return windows


class YookrSyncOrchestrator:
    """Sync sensor data from Yookr API → TimescaleDB."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = YookrClient(
            settings.yookr_base_url,
            settings.yookr_email,
            settings.yookr_password,
        )
        self._dsn = settings.tsdb_url
        self.registry = SensorRegistry()

    async def run(self) -> dict[str, Any]:
        """Execute full Yookr sync cycle."""
        start_time = datetime.now(UTC)
        stats: dict[str, Any] = {
            "endpoint": ENDPOINT_NAME,
            "total_records": 0,
            "total_created": 0,
            "sensors_synced": 0,
            "sensors_failed": 0,
            "errors": [],
        }

        pool = await init_pool(self._dsn)
        try:
            await ensure_schema(pool)

            async with pool.connection() as conn:
                state = SyncStateManager(conn, ENDPOINT_NAME)

                # Determine time range
                mode = self.settings.sync_mode.lower()
                now = datetime.now(UTC)
                if mode == "full":
                    sync_from = FULL_SYNC_START
                else:
                    sync_from = now - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
                sync_until = now

                logger.info(
                    "yookr_sync_starting",
                    mode=mode,
                    sensors=len(self.registry.all_sensors()),
                    from_date=sync_from.strftime("%Y-%m-%d"),
                    until_date=sync_until.strftime("%Y-%m-%d"),
                )

                batch: list[dict[str, Any]] = []
                latest_timestamp: datetime | None = None
                sensor_stats: dict[str, dict] = defaultdict(
                    lambda: {"count": 0, "min": None, "max": None}
                )

                windows = _generate_monthly_windows(sync_from, sync_until)

                for info in self.registry.all_sensors():
                    sensor_total = 0
                    sensor_failed = False

                    for win_start, win_end in windows:
                        try:
                            readings = self.client.fetch_readings(
                                info.sensor_id,
                                gte=win_start,
                                lte=win_end,
                                limit=500000,
                            )
                        except Exception as e:
                            logger.warning(
                                "yookr_sensor_fetch_failed",
                                sensor_id=info.sensor_id,
                                sensor_tag=info.sensor_tag,
                                device=info.device_name,
                                window=f"{win_start:%Y-%m-%d}..{win_end:%Y-%m-%d}",
                                error=str(e)[:200],
                            )
                            sensor_failed = True
                            stats["errors"].append(
                                f"{info.device_name}/{info.sensor_tag} "
                                f"({win_start:%Y-%m-%d}): {e}"
                            )
                            continue

                        if not readings:
                            continue

                        sensor_total += len(readings)

                        for r in readings:
                            params = self._reading_to_params(info, r)
                            batch.append(params)

                            dt_iso = params["datetime_measure"]
                            self._update_sensor_stats(
                                sensor_stats, info.sensor_tag, dt_iso,
                            )

                            dt = datetime.fromisoformat(
                                dt_iso.replace("Z", "+00:00")
                            )
                            if latest_timestamp is None or dt > latest_timestamp:
                                latest_timestamp = dt

                            if len(batch) >= BATCH_SIZE:
                                upserted, created = await self._flush_batch(
                                    conn, batch,
                                )
                                stats["total_records"] += upserted
                                stats["total_created"] += created
                                batch = []

                    if sensor_failed:
                        stats["sensors_failed"] += 1
                    else:
                        stats["sensors_synced"] += 1

                    logger.info(
                        "yookr_sensor_fetched",
                        sensor_tag=info.sensor_tag,
                        device=info.device_name,
                        readings=sensor_total,
                        windows=len(windows),
                    )

                # Flush remaining
                if batch:
                    upserted, created = await self._flush_batch(conn, batch)
                    stats["total_records"] += upserted
                    stats["total_created"] += created

                # Update sync state
                if stats["total_records"] > 0 and latest_timestamp is not None:
                    await state.update_timestamp(
                        latest_timestamp, stats["total_records"],
                    )

                duration = (datetime.now(UTC) - start_time).total_seconds()
                await state.record_run_result(
                    success=True,
                    duration_seconds=duration,
                    record_count=stats["total_records"],
                )
                await conn.commit()

                stats["duration_seconds"] = duration
                self._log_summary(stats, sensor_stats)

            # Refresh the continuous aggregate so dashboards see new data
            await refresh_sensor_summary(pool)

        except Exception as e:
            logger.exception("yookr_sync_failed", error=str(e))
            stats["errors"].append(str(e))
            # Try to record failure
            try:
                pool = get_pool()
                async with pool.connection() as conn:
                    state = SyncStateManager(conn, ENDPOINT_NAME)
                    await state.record_run_result(
                        success=False,
                        duration_seconds=(
                            datetime.now(UTC) - start_time
                        ).total_seconds(),
                        record_count=stats["total_records"],
                        error=str(e)[:200],
                    )
                    await conn.commit()
            except Exception:
                pass
            raise
        finally:
            await close_pool()

        return stats

    @staticmethod
    def _reading_to_params(
        info: SensorInfo, reading: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a Yookr API reading + CSV sensor info → query params."""
        dt = reading["datetimeMeasure"]
        return {
            "sensor_id": info.device_id,
            "project": "yookr-direct",
            "device_name": info.device_name,
            "sensor_tag": info.sensor_tag,
            "value": str(reading["value"]),
            "datetime_measure": dt,
            "api_timestamp": dt,  # Yookr has no separate ingest timestamp
        }

    @staticmethod
    async def _flush_batch(
        conn: Any, batch: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Flush a batch of readings to TimescaleDB."""
        if not batch:
            return 0, 0
        upserted, created = await upsert_readings(conn, batch)
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

    @staticmethod
    def _update_sensor_stats(
        sensor_stats: dict[str, dict], tag: str, dt_iso: str,
    ) -> None:
        s = sensor_stats[tag]
        s["count"] += 1
        if s["min"] is None or dt_iso < s["min"]:
            s["min"] = dt_iso
        if s["max"] is None or dt_iso > s["max"]:
            s["max"] = dt_iso

    @staticmethod
    def _log_summary(
        stats: dict[str, Any], sensor_stats: dict[str, dict],
    ) -> None:
        sensors = {
            tag: {
                "count": s["count"],
                "min_date": s["min"][:10] if s["min"] else None,
                "max_date": s["max"][:10] if s["max"] else None,
            }
            for tag, s in sorted(sensor_stats.items())
        }
        logger.info(
            "yookr_sync_complete",
            total_fetched=stats["total_records"],
            total_created=stats["total_created"],
            total_duplicates=stats["total_records"] - stats["total_created"],
            sensors_synced=stats["sensors_synced"],
            sensors_failed=stats["sensors_failed"],
            duration=f"{stats.get('duration_seconds', 0):.1f}s",
            by_tag=sensors,
        )
