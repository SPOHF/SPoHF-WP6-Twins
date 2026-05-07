"""TimescaleDB schema bootstrap for the red twin (manual_uploads + readings).

Mirrors the column shape of blue's `readings` table, except `project` is
renamed to `source` and a nullable `upload_id` foreign key links rows that
came from a manual Excel upload back to their `manual_uploads` audit row.
"""

import structlog
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
