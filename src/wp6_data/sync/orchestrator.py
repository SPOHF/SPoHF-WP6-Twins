"""Main sync orchestration logic."""

from datetime import UTC, datetime
from typing import Any

import structlog

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

BATCH_SIZE = 100  # Records per Neo4j transaction


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
        async with self.neo4j.session() as session:
            state = SyncStateManager(session, endpoint)
            since, is_initial = await state.get_last_timestamp_with_status(
                self.settings.sync_lookback_hours
            )

            logger.info(
                "sync_starting",
                endpoint=endpoint,
                since=since.isoformat(),
                mode="windowed" if is_initial else "incremental",
            )

            batch: list[dict[str, Any]] = []
            latest_timestamp = since
            total_count = 0

            # Use windowed fetch for initial sync, regular for incremental
            if is_initial:
                fetch_iter = self.client.fetch_all_windowed(
                    endpoint,
                    since,
                    max_windows=50,
                )
            else:
                fetch_iter = self.client.fetch_all_since(
                    endpoint,
                    since,
                    self.settings.sync_max_pages,
                )

            async for reading in fetch_iter:
                batch.append(self._reading_to_params(reading))

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

            logger.info(
                "endpoint_synced",
                endpoint=endpoint,
                records=total_count,
                latest=latest_timestamp.isoformat(),
            )
            return total_count

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
