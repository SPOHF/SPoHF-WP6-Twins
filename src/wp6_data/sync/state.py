"""Sync state management stored in Neo4j."""

from datetime import UTC, datetime, timedelta

from neo4j import AsyncSession


class SyncStateManager:
    """Manage sync state using Neo4j SyncMetadata nodes.

    Stores last successful sync timestamp per endpoint to enable
    incremental syncing.
    """

    def __init__(self, session: AsyncSession, endpoint: str):
        self._session = session
        self._endpoint = endpoint

    async def get_last_timestamp(self, default_lookback_hours: int = 24) -> datetime:
        """Get last successful sync timestamp.

        Returns the stored timestamp, or (now - lookback_hours) if no
        previous sync exists.
        """
        ts, _ = await self.get_last_timestamp_with_status(default_lookback_hours)
        return ts

    async def get_last_timestamp_with_status(
        self, default_lookback_hours: int = 24
    ) -> tuple[datetime, bool]:
        """Get last successful sync timestamp and whether this is initial sync.

        Returns:
            Tuple of (timestamp, is_initial_sync)
        """
        result = await self._session.run(
            """
            MATCH (m:SyncMetadata {endpoint: $endpoint})
            RETURN m.last_timestamp AS ts
            """,
            endpoint=self._endpoint,
        )
        record = await result.single()

        if record and record["ts"]:
            # Neo4j returns neo4j.time.DateTime, convert to Python datetime
            neo4j_dt = record["ts"]
            return neo4j_dt.to_native(), False

        # Default: look back N hours from now (initial sync)
        return datetime.now(UTC) - timedelta(hours=default_lookback_hours), True

    async def update_timestamp(
        self,
        timestamp: datetime,
        record_count: int,
    ) -> None:
        """Update sync metadata after successful batch.

        Args:
            timestamp: The latest datetime_measure we synced
            record_count: Number of records processed in this run
        """
        await self._session.run(
            """
            MERGE (m:SyncMetadata {endpoint: $endpoint})
            SET m.last_timestamp = datetime($ts),
                m.last_run_at = datetime(),
                m.records_processed = $count
            """,
            endpoint=self._endpoint,
            ts=timestamp.isoformat(),
            count=record_count,
        )

    async def record_run_result(
        self,
        *,
        success: bool,
        duration_seconds: float,
        record_count: int,
        error: str | None = None,
        api_status: int | None = None,
        api_error_detail: str | None = None,
    ) -> None:
        """Record the result of a sync run for observability.

        Args:
            success: Whether the sync completed successfully
            duration_seconds: How long the sync took
            record_count: Number of records processed
            error: Error message if failed
            api_status: HTTP status code if API error
            api_error_detail: Response body snippet if API error
        """
        await self._session.run(
            """
            MERGE (m:SyncMetadata {endpoint: $endpoint})
            SET m.last_run_at = datetime(),
                m.last_run_success = $success,
                m.last_run_duration_seconds = $duration,
                m.last_run_records = $records,
                m.total_runs = coalesce(m.total_runs, 0) + 1,
                m.total_failures = CASE WHEN $success THEN coalesce(m.total_failures, 0)
                                        ELSE coalesce(m.total_failures, 0) + 1 END
            WITH m
            WHERE NOT $success
            SET m.last_error = $error,
                m.last_api_status = $api_status,
                m.last_api_error_detail = $api_detail
            """,
            endpoint=self._endpoint,
            success=success,
            duration=duration_seconds,
            records=record_count,
            error=error,
            api_status=api_status,
            api_detail=api_error_detail,
        )
