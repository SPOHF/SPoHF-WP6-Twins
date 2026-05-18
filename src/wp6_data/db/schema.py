"""TimescaleDB schema helpers shared by both twins.

The `readings` table itself diverges between blue and red (column names, dedup
key, presence of `upload_id`), so each twin owns its own readings DDL. This
module owns the twin-agnostic parts:

* `MANUAL_UPLOADS_SQL` — the `manual_uploads` audit table, the permanent
  system of record for every manual upload, identical between twins.
* `AUX_SCHEMA_SQL` — `sync_metadata` and `daily_coverage` tables, identical
  between twins.
* `CAGG_SQL_TEMPLATE` — the `sensors_daily_summary` continuous aggregate,
  parameterised by the categorical column name on a twin's `readings`
  table (a twin with multiple parallel automated pipelines uses a different
  column than one keyed only by provenance).

Twin code calls `ensure_aggregates(pool, project_column=...)` after creating
its own `readings` hypertable.
"""

import structlog
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

# The manual-upload audit trail. Twin-agnostic: the `source` column here is
# the upload slug, not the readings categorical column. Pruning nulls
# `file_path`/sets `file_pruned`; the row itself is never deleted.
MANUAL_UPLOADS_SQL = """
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
"""

# Blue's readings gains the same nullable FK red's readings has, added
# idempotently. Adding a nullable column with no default is metadata-only on
# the hypertable; the FK targets the plain `manual_uploads` table, so it is
# valid on a hypertable (the referencing side may be a hypertable). IF NOT
# EXISTS makes the whole clause — column and its inline FK — idempotent.
BLUE_UPLOAD_ID_SQL = """
ALTER TABLE readings
    ADD COLUMN IF NOT EXISTS upload_id BIGINT REFERENCES manual_uploads(id);
"""

# Blue's manual-ingest categorical, mirroring red's `source` column. Distinct
# from `project` (the automated yookr-vs-datalake view): automated rows keep
# the 'unknown' default; a manual upload sets it (e.g. 'insects'). Added
# idempotently for existing blue databases (metadata-only, like upload_id).
BLUE_SOURCE_SQL = """
ALTER TABLE readings
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_readings_manual_source
    ON readings (source) WHERE source <> 'unknown';
"""

# Blue's readings hypertable. Red has its own DDL in `wp6_data.red.tsdb`.
READINGS_BLUE_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    time        TIMESTAMPTZ      NOT NULL,
    device_name TEXT             NOT NULL,
    sensor_tag  TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    raw_value   TEXT,
    project     TEXT             NOT NULL DEFAULT 'unknown',
    source      TEXT             NOT NULL DEFAULT 'unknown',
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
    async with pool.connection() as conn:
        await conn.execute(CAGG_SQL_TEMPLATE.format(project_column=project_column))
        await conn.commit()
    # Background refresh policy: TimescaleDB's scheduler refreshes the cagg
    # incrementally over a sliding window, independent of sync. start_offset
    # matches INCREMENTAL_LOOKBACK_DAYS in sync/orchestrator.py — keep them
    # in sync. Whole-history refresh is only needed after WP6_SYNC_MODE=full
    # (handled in the orchestrator) or after a manual cagg recreate (runbook
    # step: CALL refresh_continuous_aggregate('sensors_daily_summary',NULL,NULL)).
    # try/finally resets autocommit before the connection returns to the pool
    # — psycopg-pool does not reset client-side autocommit, and leaving it on
    # would break manual-commit callers like Sijia's transactional apply().
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        try:
            await conn.execute(
                "SELECT add_continuous_aggregate_policy("
                "'sensors_daily_summary',"
                " start_offset => INTERVAL '7 days',"
                " end_offset   => INTERVAL '1 hour',"
                " schedule_interval => INTERVAL '15 minutes',"
                " if_not_exists => TRUE)"
            )
        finally:
            await conn.set_autocommit(False)
    logger.info("aggregates_ensured", project_column=project_column)


async def ensure_schema(pool: AsyncConnectionPool) -> None:
    """Ensure blue's full TSDB schema (manual_uploads + readings + FK + cagg).

    Order matters: ``manual_uploads`` must exist before the ``upload_id`` FK
    is added to ``readings``. All idempotent — safe to run on every startup,
    including on a pre-existing blue database (the ALTER is a no-op once the
    column exists).
    """
    async with pool.connection() as conn:
        await conn.execute(MANUAL_UPLOADS_SQL)
        await conn.execute(READINGS_BLUE_SQL)
        await conn.execute(BLUE_UPLOAD_ID_SQL)
        await conn.execute(BLUE_SOURCE_SQL)
        await conn.commit()
    await ensure_aggregates(pool, project_column="project")
    logger.info("tsdb_schema_ensured")
