"""TimescaleDB schema for blue sensor data."""

import structlog
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    time        TIMESTAMPTZ      NOT NULL,
    device_name TEXT             NOT NULL,
    sensor_tag  TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    raw_value   TEXT,
    project     TEXT             NOT NULL DEFAULT 'unknown',
    synced_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- Hypertable (idempotent via if_not_exists)
SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_readings_device_tag
    ON readings (device_name, sensor_tag, time DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup
    ON readings (device_name, sensor_tag, time);

CREATE TABLE IF NOT EXISTS sync_metadata (
    endpoint              TEXT PRIMARY KEY,
    last_timestamp        TIMESTAMPTZ,
    last_run_at           TIMESTAMPTZ,
    last_run_success      BOOLEAN,
    last_run_duration_sec DOUBLE PRECISION,
    last_run_records      INTEGER,
    last_error            TEXT,
    last_api_status       INTEGER,
    last_api_error_detail TEXT,
    total_runs            INTEGER DEFAULT 0,
    total_failures        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_coverage (
    device_name TEXT NOT NULL,
    sensor_tag  TEXT NOT NULL,
    day         DATE NOT NULL,
    PRIMARY KEY (device_name, sensor_tag, day)
);
"""


async def ensure_schema(pool: AsyncConnectionPool) -> None:
    """Run schema DDL idempotently."""
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.commit()
    logger.info("tsdb_schema_ensured")
