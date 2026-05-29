"""SQL queries for TimescaleDB operations."""

from datetime import datetime
from typing import Any

import structlog
from psycopg import AsyncConnection
from psycopg.rows import dict_row

logger = structlog.get_logger()


async def upsert_readings(
    conn: AsyncConnection,
    readings: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert a batch of readings into TimescaleDB.

    Args:
        conn: psycopg async connection
        readings: List of dicts with keys:
            sensor_id, project, device_name, sensor_tag,
            value, datetime_measure, api_timestamp

    Returns:
        Tuple of (total upserted, newly created)
    """
    if not readings:
        return 0, 0

    query = (
        "INSERT INTO readings (time, device_name, sensor_tag, value, raw_value, project)"
        " VALUES ("
        "  %(datetime_measure)s, %(device_name)s, %(sensor_tag)s,"
        r"  CASE WHEN %(value)s ~ '^-?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$'"
        "       THEN %(value)s::double precision"
        "       ELSE NULL"
        "  END,"
        "  %(value)s, %(project)s"
        " )"
        " ON CONFLICT (device_name, sensor_tag, time)"
        " DO UPDATE SET value = EXCLUDED.value,"
        "              raw_value = EXCLUDED.raw_value,"
        "              synced_at = NOW()"
    )

    async with conn.cursor() as cur:
        created = 0
        for r in readings:
            await cur.execute(query, r)
            # statusmessage is "INSERT 0 1" for insert, "UPDATE 0 1" for update
            if cur.statusmessage and cur.statusmessage.startswith("INSERT"):
                created += 1

    return len(readings), created


async def upsert_daily_coverage(
    conn: AsyncConnection,
    records: list[dict[str, str]],
) -> int:
    """Upsert daily_coverage rows.

    Args:
        conn: psycopg async connection
        records: List of dicts with keys: device_name, sensor_tag, source,
            day (ISO date string). ``source`` mirrors ``readings.source`` so the
            status page can classify manual vs automated coverage.

    Returns:
        Number of rows touched
    """
    if not records:
        return 0

    query = """
        INSERT INTO daily_coverage (device_name, sensor_tag, source, day)
        VALUES (%(device_name)s, %(sensor_tag)s, %(source)s, %(day)s)
        ON CONFLICT DO NOTHING
    """
    async with conn.cursor() as cur:
        for r in records:
            await cur.execute(query, r)

    return len(records)


async def rebuild_daily_coverage(conn: AsyncConnection) -> int:
    """Rebuild daily_coverage from all readings.

    Returns:
        Total number of coverage entries after rebuild
    """
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM daily_coverage")
        await cur.execute("""
            INSERT INTO daily_coverage (device_name, sensor_tag, source, day)
            SELECT DISTINCT device_name, sensor_tag, source, time::date
            FROM readings
            ON CONFLICT DO NOTHING
        """)
        await cur.execute("SELECT count(*) FROM daily_coverage")
        row = await cur.fetchone()
        return row[0] if row else 0


async def record_sync_run(
    conn: AsyncConnection,
    endpoint: str,
    *,
    success: bool,
    duration_sec: float,
    records: int,
    last_timestamp: datetime | None = None,
    error: str | None = None,
) -> None:
    """Upsert one row in `sync_metadata` for a job-run audit log entry.

    Increments `total_runs` always, `total_failures` only when `success` is
    false. On success, prior error fields are preserved (use a follow-up
    successful run to clear stale errors only via explicit policy).

    Endpoint is a free-form string — treat it as a generic job identifier
    (e.g. ``"sijia"``, ``"red-export"``, ``"yookr-data"``).
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO sync_metadata (
                endpoint, last_timestamp, last_run_at, last_run_success,
                last_run_duration_sec, last_run_records,
                total_runs, total_failures, last_error
            )
            VALUES (
                %(endpoint)s, %(last_ts)s, NOW(), %(success)s,
                %(duration)s, %(records)s,
                1, %(failure_inc)s, %(error)s
            )
            ON CONFLICT (endpoint) DO UPDATE SET
                last_timestamp = COALESCE(EXCLUDED.last_timestamp, sync_metadata.last_timestamp),
                last_run_at = NOW(),
                last_run_success = %(success)s,
                last_run_duration_sec = %(duration)s,
                last_run_records = %(records)s,
                total_runs = COALESCE(sync_metadata.total_runs, 0) + 1,
                total_failures = COALESCE(sync_metadata.total_failures, 0) + %(failure_inc)s,
                last_error = CASE WHEN %(success)s THEN sync_metadata.last_error
                                  ELSE %(error)s END
            """,
            {
                "endpoint": endpoint,
                "last_ts": last_timestamp,
                "success": success,
                "duration": duration_sec,
                "records": records,
                "failure_inc": 0 if success else 1,
                "error": error,
            },
        )


async def fetch_manual_summary(pool: Any) -> dict[str, Any]:
    """Twin-agnostic manual-upload freshness for the home/status pages.

    Returns ``{"uploads": {slug: last_uploaded_at},
              "measurements": {sensor_tag: last_measure_time}}``.

    Groups ``manual_uploads`` by its ``source`` slug and finds the latest
    reading time for rows that carry an ``upload_id`` (i.e. came from a
    manual upload). Depends only on ``manual_uploads`` + ``readings.upload_id``,
    so it is the same query for any twin.
    """
    async with pool.connection() as conn, conn.cursor(
        row_factory=dict_row,
    ) as cur:
        await cur.execute(
            "SELECT source, MAX(uploaded_at) AS last_upload "
            "FROM manual_uploads GROUP BY source",
        )
        upload_rows = await cur.fetchall()
        await cur.execute(
            "SELECT r.sensor_tag, MAX(r.time) AS last_measure "
            "FROM readings r WHERE r.upload_id IS NOT NULL "
            "GROUP BY r.sensor_tag",
        )
        measure_rows = await cur.fetchall()

    return {
        "uploads": {r["source"]: r["last_upload"] for r in upload_rows},
        "measurements": {
            r["sensor_tag"]: r["last_measure"] for r in measure_rows
        },
    }


async def refresh_sensor_summary(pool: Any) -> None:
    """Refresh the sensors_daily_summary continuous aggregate over its whole
    history. Heavy on large datasets — reserve for mode=full sync or manual
    rebuild. The try/finally resets autocommit before the connection returns
    to the pool, since psycopg-pool does not reset client-side autocommit
    state and other callers (e.g. Sijia's transactional apply) rely on the
    pool default of manual-commit mode.
    """
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        try:
            await conn.execute(
                "CALL refresh_continuous_aggregate("
                "'sensors_daily_summary', NULL, NULL)"
            )
        finally:
            await conn.set_autocommit(False)
    logger.info("sensors_daily_summary_refreshed", scope="whole_history")


async def refresh_sensor_summary_recent(pool: Any) -> None:
    """Refresh the sensors_daily_summary cagg over the last 2 days of buckets.

    Used at the tail of incremental sync so dashboards see freshly-written
    data immediately. 2 days covers the sync's 1-day window plus a margin
    for clock skew / TZ edges, and the work is bounded (~2 daily buckets)
    regardless of dataset size. The background refresh policy still handles
    the broader 7-day window on its own schedule.
    """
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        try:
            await conn.execute(
                "CALL refresh_continuous_aggregate("
                "'sensors_daily_summary',"
                " NOW() - INTERVAL '2 days', NULL)"
            )
        finally:
            await conn.set_autocommit(False)
    logger.info("sensors_daily_summary_refreshed", scope="last_2d")
