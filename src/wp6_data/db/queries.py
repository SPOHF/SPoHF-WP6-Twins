"""SQL queries for TimescaleDB operations."""

from typing import Any

import structlog
from psycopg import AsyncConnection

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
        records: List of dicts with keys: device_name, sensor_tag, day (ISO date string)

    Returns:
        Number of rows touched
    """
    if not records:
        return 0

    query = """
        INSERT INTO daily_coverage (device_name, sensor_tag, day)
        VALUES (%(device_name)s, %(sensor_tag)s, %(day)s)
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
            INSERT INTO daily_coverage (device_name, sensor_tag, day)
            SELECT DISTINCT device_name, sensor_tag, time::date
            FROM readings
            ON CONFLICT DO NOTHING
        """)
        await cur.execute("SELECT count(*) FROM daily_coverage")
        row = await cur.fetchone()
        return row[0] if row else 0


async def refresh_sensor_summary(pool: Any) -> None:
    """Refresh the sensors_daily_summary continuous aggregate.

    Call this after syncing new data so the cagg is immediately up to date.
    """
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        await conn.execute(
            "CALL refresh_continuous_aggregate('sensors_daily_summary', NULL, NULL)"
        )
    logger.info("sensors_daily_summary_refreshed")
