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

# Continuous aggregate: pre-aggregated sensor summary per day.
# Kept separate from SCHEMA_SQL because CREATE MATERIALIZED VIEW … WITH
# (timescaledb.continuous) cannot run inside a multi-statement string that
# also creates the underlying hypertable in the same transaction.
CAGG_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS sensors_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    device_name,
    sensor_tag,
    project,
    count(*)    AS reading_count,
    min(time)   AS first_reading,
    max(time)   AS last_reading
FROM readings
GROUP BY bucket, device_name, sensor_tag, project
WITH NO DATA;
"""





async def ensure_schema(pool: AsyncConnectionPool) -> None:
    """Run schema DDL idempotently."""
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.commit()
    # Continuous aggregate must be created after the hypertable exists,
    # in its own transaction.  No background policy — the sync jobs
    # call refresh_sensor_summary() explicitly after inserting data.
    async with pool.connection() as conn:
        await conn.execute(CAGG_SQL)
        await conn.commit()
    logger.info("tsdb_schema_ensured")
