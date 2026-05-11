"""TimescaleDB schema helpers shared by both twins.

The `readings` table itself diverges between blue and red (column names, dedup
key, presence of `upload_id`), so each twin owns its own readings DDL. This
module owns the twin-agnostic parts:

* `AUX_SCHEMA_SQL` — `sync_metadata` and `daily_coverage` tables, identical
  between twins.
* `CAGG_SQL_TEMPLATE` — the `sensors_daily_summary` continuous aggregate. The
  template is parameterised by the categorical column name on `readings`
  (blue uses ``project``, red uses ``source`` — see
  ``project_blue_project_vs_red_source`` memo for why these are different
  concepts, not aliases).

Twin code calls `ensure_aggregates(pool, project_column=...)` after creating
its own `readings` hypertable.
"""

import structlog
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

# Blue's readings hypertable. Red has its own DDL in `wp6_data.red.tsdb`.
READINGS_BLUE_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    time        TIMESTAMPTZ      NOT NULL,
    device_name TEXT             NOT NULL,
    sensor_tag  TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    raw_value   TEXT,
    project     TEXT             NOT NULL DEFAULT 'unknown',
    synced_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_readings_device_tag
    ON readings (device_name, sensor_tag, time DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup
    ON readings (device_name, sensor_tag, time);
"""

AUX_SCHEMA_SQL = """
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

# Continuous aggregate template. `{project_column}` is the categorical column
# on the twin's `readings` table (blue: `project`, red: `source`). Both are
# valid SQL identifiers; callers are trusted to pass a known constant.
CAGG_SQL_TEMPLATE = """
CREATE MATERIALIZED VIEW IF NOT EXISTS sensors_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    device_name,
    sensor_tag,
    {project_column} AS project,
    count(*)    AS reading_count,
    min(time)   AS first_reading,
    max(time)   AS last_reading
FROM readings
GROUP BY bucket, device_name, sensor_tag, {project_column}
WITH NO DATA;
"""


async def ensure_aggregates(
    pool: AsyncConnectionPool, *, project_column: str
) -> None:
    """Create twin-agnostic aux tables + the sensors_daily_summary cagg.

    Idempotent. Must be called after the twin's `readings` hypertable exists.
    The continuous aggregate aliases the twin's categorical column to ``project``
    so consumers see a uniform shape regardless of which twin produced it.
    """
    async with pool.connection() as conn:
        await conn.execute(AUX_SCHEMA_SQL)
        await conn.commit()
    # Continuous aggregate must be created in its own transaction after the
    # hypertable exists. No background refresh policy — call sites refresh
    # explicitly via refresh_sensor_summary() after writing data.
    async with pool.connection() as conn:
        await conn.execute(CAGG_SQL_TEMPLATE.format(project_column=project_column))
        await conn.commit()
    logger.info("aggregates_ensured", project_column=project_column)


async def ensure_schema(pool: AsyncConnectionPool) -> None:
    """Ensure blue's full TSDB schema (readings + aux tables + cagg)."""
    async with pool.connection() as conn:
        await conn.execute(READINGS_BLUE_SQL)
        await conn.commit()
    await ensure_aggregates(pool, project_column="project")
    logger.info("tsdb_schema_ensured")
