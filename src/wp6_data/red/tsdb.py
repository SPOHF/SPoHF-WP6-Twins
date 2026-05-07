"""TimescaleDB schema bootstrap and read helpers for the red twin.

Mirrors the column shape of blue's `readings` table, except `project` is
renamed to `source` and a nullable `upload_id` foreign key links rows that
came from a manual Excel upload back to their `manual_uploads` audit row.

Read helpers (`fetch_*_tsdb`) are used by the federated `RedSensorProvider`
to serve sensor_tags whose `source` is set in metadata.yaml.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manual_uploads (
    id          BIGSERIAL    PRIMARY KEY,
    source      TEXT         NOT NULL,
    filename    TEXT         NOT NULL,
    file_hash   TEXT         NOT NULL,
    file_path   TEXT,
    file_pruned BOOLEAN      NOT NULL DEFAULT FALSE,
    uploaded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    row_count   INTEGER      NOT NULL,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    time        TIMESTAMPTZ      NOT NULL,
    device_name TEXT             NOT NULL,
    sensor_tag  TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    raw_value   TEXT,
    source      TEXT             NOT NULL DEFAULT 'unknown',
    synced_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    upload_id   BIGINT           REFERENCES manual_uploads(id)
);

SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_readings_device_tag
    ON readings (device_name, sensor_tag, time DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup
    ON readings (source, device_name, sensor_tag, time);
"""


async def ensure_schema_red(pool: AsyncConnectionPool) -> None:
    """Run red TSDB schema DDL idempotently."""
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.commit()
    logger.info("red_tsdb_schema_ensured")


_EMPTY_READINGS = pd.DataFrame(columns=["device", "sensor", "time", "value"])


async def fetch_data_tsdb(
    sensor_tags: list[str] | None = None,
    device_names: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500_000,
) -> pd.DataFrame:
    """Fetch readings from the red TSDB `readings` table.

    Returns DataFrame with columns: device, sensor, time, value.
    """
    from wp6_data.db.pool import get_pool

    if not sensor_tags:
        return _EMPTY_READINGS.copy()

    conditions = ["sensor_tag = ANY(%(tags)s)"]
    params: dict[str, Any] = {"tags": sensor_tags}
    if device_names:
        conditions.append("device_name = ANY(%(devices)s)")
        params["devices"] = device_names
    if start:
        conditions.append("time >= %(start)s")
        params["start"] = start
    if end:
        conditions.append("time <= %(end)s")
        params["end"] = end
    params["limit"] = limit

    where = " AND ".join(conditions)
    query = f"""
        SELECT device_name AS device, sensor_tag AS sensor, time, value
        FROM readings
        WHERE {where}
        ORDER BY time
        LIMIT %(limit)s
    """

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        records = await cur.fetchall()

    if not records:
        return _EMPTY_READINGS.copy()
    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("time")


async def fetch_device_counts_tsdb() -> dict[str, int]:
    """Total row count per device_name in the red `readings` table.

    Used by RedSensorProvider to populate the home page's reading-count
    column for TSDB-backed devices (matches the MySQL side, which sums
    COUNT(*) per device across legacy sensor tables).
    """
    from wp6_data.db.pool import get_pool

    query = """
        SELECT device_name, count(*) AS n
        FROM readings
        GROUP BY device_name
    """
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        rows = await cur.fetchall()
    return {r["device_name"]: r["n"] for r in rows}


async def fetch_daily_coverage_tsdb() -> list[dict[str, Any]]:
    """Distinct (device, sensor, day) triples from the red `readings` table."""
    from wp6_data.db.pool import get_pool

    query = """
        SELECT device_name AS device, sensor_tag AS sensor,
               DATE(time) AS day
        FROM readings
        GROUP BY device_name, sensor_tag, DATE(time)
        ORDER BY device, sensor, day
    """
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        return list(await cur.fetchall())
