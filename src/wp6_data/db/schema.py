"""TimescaleDB schema helpers shared by both twins.

The `readings` table itself diverges between blue and red (column names, dedup
key, presence of `upload_id`), so each twin owns its own readings DDL. This
module owns the twin-agnostic parts:

* `MANUAL_UPLOADS_SQL` — the `manual_uploads` audit table, the permanent
  system of record for every manual upload, identical between twins.
* `AUX_SCHEMA_SQL` — the `sync_metadata` table, identical between twins.
* `CAGG_SQL` — the `sensors_daily_summary` continuous aggregate. Both twins
  key `readings` on a single `source` categorical, so it is not parameterised.

Twin code calls `ensure_aggregates(pool)` after creating
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

-- Current-failure-streak tracking (added idempotently for existing DBs). Unlike
-- the lifetime `total_failures`, these reset to NULL/0 on the next success, so
-- the status page can say "failing since X (N runs)" and stop showing a stale
-- error once a run recovers.
ALTER TABLE sync_metadata ADD COLUMN IF NOT EXISTS failing_since TIMESTAMPTZ;
ALTER TABLE sync_metadata ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;

-- One row per sync run — the granular history sync_metadata (one row per
-- endpoint) cannot hold. Feeds the status page's rolling SLA, "X of last Y",
-- and per-run record sparkline. Append-only, pruned to SYNC_HISTORY_RETENTION.
CREATE TABLE IF NOT EXISTS sync_run_history (
    endpoint     TEXT             NOT NULL,
    run_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    success      BOOLEAN          NOT NULL,
    records      INTEGER,
    duration_sec DOUBLE PRECISION,
    api_status   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sync_run_history_endpoint_time
    ON sync_run_history (endpoint, run_at DESC);

-- The `daily_coverage` table was retired: coverage is now read straight from
-- the `sensors_daily_summary` cagg, which carries the same (device, sensor,
-- day, source) and refreshes as readings change. Drop it if present.
DROP TABLE IF EXISTS daily_coverage;
"""

# Rows older than this are pruned from sync_run_history on each write. At the
# 15-min cadence (~96 runs/day/endpoint) that is ~2,900 rows per endpoint.
SYNC_HISTORY_RETENTION = "30 days"

# Continuous aggregate over each twin's `readings`. Both twins carry the same
# single categorical (`source`) since blue dropped `project`, so the cagg groups
# by it directly — no per-twin column parameter.
CAGG_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS sensors_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    device_name,
    sensor_tag,
    source,
    count(*)    AS reading_count,
    min(time)   AS first_reading,
    max(time)   AS last_reading
FROM readings
GROUP BY bucket, device_name, sensor_tag, source
WITH NO DATA;
"""


async def ensure_aggregates(pool: AsyncConnectionPool) -> None:
    """Create twin-agnostic aux tables + the sensors_daily_summary cagg.

    Idempotent. Must be called after the twin's `readings` hypertable exists.
    """
    async with pool.connection() as conn:
        await conn.execute(AUX_SCHEMA_SQL)
        await conn.commit()
    async with pool.connection() as conn:
        await conn.execute(CAGG_SQL)
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
    logger.info("aggregates_ensured")
