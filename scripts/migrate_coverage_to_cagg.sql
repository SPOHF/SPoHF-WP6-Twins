-- Rename the cagg categorical from `project` to `source`, in preparation for the
-- merge "refactor(db): collapse daily_coverage into the cagg".
--
-- Run ONCE against each twin's database, DURING the image build (i.e. BEFORE the
-- new image deploys). The OLD code never selects the cagg's categorical column by
-- name, so a source-named cagg is transparent to it — running this ahead of the
-- deploy means the new code lands on a cagg that already has the column it reads,
-- with zero coverage downtime.
--
-- This does NOT drop `daily_coverage`: the old code still reads that table, so it
-- must survive until the new image is running. The new image's `ensure_schema`
-- drops it at startup (AUX_SCHEMA_SQL: `DROP TABLE IF EXISTS daily_coverage`).
--
-- Safe to re-run. The whole-history refresh is the slow part (~1-2 min on blue's
-- 5.3M rows).
--
-- Usage:
--   kubectl --context old -n spohf-system exec -i wp6-data-timescaledb-0 -- \
--     psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f - < scripts/migrate_coverage_to_cagg.sql

\set ON_ERROR_STOP on
\timing on

-- 1. Rebuild the cagg with `source` as the categorical (was aliased `project`).
--    A materialized view's output column can't be renamed in place.
DROP MATERIALIZED VIEW IF EXISTS sensors_daily_summary CASCADE;

CREATE MATERIALIZED VIEW sensors_daily_summary
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

-- 2. Reinstate the background refresh policy (dropped with the view).
SELECT add_continuous_aggregate_policy(
    'sensors_daily_summary',
    start_offset      => INTERVAL '7 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists     => TRUE);

-- 3. Materialise the whole history (the view is created WITH NO DATA).
CALL refresh_continuous_aggregate('sensors_daily_summary', NULL, NULL);

SELECT count(*) AS cagg_rows FROM sensors_daily_summary;
