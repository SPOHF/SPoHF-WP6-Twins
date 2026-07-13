"""Sync state management stored in TimescaleDB."""

from datetime import UTC, datetime, timedelta

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from wp6_data.db.schema import SYNC_HISTORY_RETENTION


class SyncStateManager:
    """Manage sync state using the sync_metadata table.

    Stores last successful sync timestamp per endpoint to enable
    incremental syncing.
    """

    def __init__(self, conn: AsyncConnection, endpoint: str):
        self._conn = conn
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
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT last_timestamp FROM sync_metadata WHERE endpoint = %(endpoint)s",
                {"endpoint": self._endpoint},
            )
            row = await cur.fetchone()

        if row and row["last_timestamp"]:
            return row["last_timestamp"], False

        # Default: look back N hours from now (initial sync)
        return datetime.now(UTC) - timedelta(hours=default_lookback_hours), True

    async def update_timestamp(
        self,
        timestamp: datetime,
        record_count: int,
    ) -> None:
        """Update sync metadata after successful batch."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO sync_metadata (endpoint, last_timestamp, last_run_at, last_run_records)
                VALUES (%(endpoint)s, %(ts)s, NOW(), %(count)s)
                ON CONFLICT (endpoint) DO UPDATE SET
                    last_timestamp = %(ts)s,
                    last_run_at = NOW(),
                    last_run_records = %(count)s
                """,
                {"endpoint": self._endpoint, "ts": timestamp, "count": record_count},
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

        On success the transient error fields and the failure streak are cleared,
        so a recovered endpoint stops showing a stale error (the lifetime
        `total_failures` is kept, and the full history lives in
        ``sync_run_history``). On failure the streak's `failing_since` is set once
        and preserved until the next success.
        """
        params = {
            "endpoint": self._endpoint,
            "success": success,
            "duration": duration_seconds,
            "records": record_count,
            "failure_inc": 0 if success else 1,
            "error": error,
            "api_status": api_status,
            "api_detail": api_error_detail,
            "retention": SYNC_HISTORY_RETENTION,
        }
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO sync_metadata (
                    endpoint, last_run_at, last_run_success,
                    last_run_duration_sec, last_run_records,
                    total_runs, total_failures, consecutive_failures, failing_since,
                    last_error, last_api_status, last_api_error_detail
                )
                VALUES (
                    %(endpoint)s, NOW(), %(success)s,
                    %(duration)s, %(records)s,
                    1, %(failure_inc)s, %(failure_inc)s,
                    CASE WHEN %(success)s THEN NULL ELSE NOW() END,
                    %(error)s, %(api_status)s, %(api_detail)s
                )
                ON CONFLICT (endpoint) DO UPDATE SET
                    last_run_at = NOW(),
                    last_run_success = %(success)s,
                    last_run_duration_sec = %(duration)s,
                    last_run_records = %(records)s,
                    total_runs = COALESCE(sync_metadata.total_runs, 0) + 1,
                    total_failures = COALESCE(sync_metadata.total_failures, 0) + %(failure_inc)s,
                    consecutive_failures = CASE WHEN %(success)s THEN 0
                        ELSE COALESCE(sync_metadata.consecutive_failures, 0) + 1 END,
                    failing_since = CASE WHEN %(success)s THEN NULL
                        ELSE COALESCE(sync_metadata.failing_since, NOW()) END,
                    last_error = CASE WHEN %(success)s THEN NULL ELSE %(error)s END,
                    last_api_status = CASE WHEN %(success)s THEN NULL ELSE %(api_status)s END,
                    last_api_error_detail = CASE WHEN %(success)s THEN NULL ELSE %(api_detail)s END
                """,
                params,
            )
            await cur.execute(
                """
                INSERT INTO sync_run_history
                    (endpoint, success, records, duration_sec, api_status)
                VALUES (%(endpoint)s, %(success)s, %(records)s, %(duration)s, %(api_status)s)
                """,
                params,
            )
            await cur.execute(
                "DELETE FROM sync_run_history "
                "WHERE endpoint = %(endpoint)s "
                f"  AND run_at < NOW() - INTERVAL '{SYNC_HISTORY_RETENTION}'",
                {"endpoint": self._endpoint},
            )
