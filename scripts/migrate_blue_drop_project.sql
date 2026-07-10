-- Retire yookr-direct: purge its rows and drop readings.project.
--
-- Converges blue on red's single-categorical model. Run ONCE, against the blue
-- database, BETWEEN two deploys:
--
--   1. The currently-running image still SELECTs `project`; it will 500 from the
--      moment step 5 commits until the new image rolls. Expect ~2 min of errors.
--   2. The new image REFUSES to boot while `project` exists (see
--      blue/tsdb.py::ensure_schema_blue), so it cannot start before this runs.
--
-- Full context, sequence and rollback: docs/blue/yookr-direct-retirement.md
--
-- Preconditions (do NOT skip):
--   * The truncation backfill has completed (docs: ~280k rows recovered), so the
--     datalake owns every reading it can. Verify no series is yookr-only.
--   * The sync CronJob is disabled (`sync.enabled: false` in helm values, synced
--     by argocd — a manual `kubectl patch --suspend` gets reverted).
--   * `\copy (SELECT * FROM readings WHERE project='yookr-direct') TO 'yookr.csv' CSV HEADER`
--     has been taken and its row count matches the count below. This is the only
--     way back.
--
-- Usage:
--   kubectl --context old -n spohf-system exec -i wp6-data-timescaledb-0 -- \
--     psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f - < scripts/migrate_blue_drop_project.sql

\set ON_ERROR_STOP on
\timing on

-- ---------------------------------------------------------------------------
-- 0. Refuse to run if any series exists ONLY under yookr-direct. Purging those
--    would delete readings nothing else holds. (Expected: 0 rows.)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    orphans int;
BEGIN
    SELECT count(*) INTO orphans
    FROM (
        SELECT device_name, sensor_tag
        FROM readings
        WHERE project IN ('yookr-direct', 'spohf-datalake')
        GROUP BY device_name, sensor_tag
        HAVING count(*) FILTER (WHERE project = 'spohf-datalake') = 0
    ) s;

    IF orphans > 0 THEN
        RAISE EXCEPTION
            'ABORT: % (device, sensor) series exist only under yookr-direct. '
            'Purging would lose them permanently. Investigate before proceeding.',
            orphans;
    END IF;
END $$;

-- Record what we are about to destroy, so it lands in the operator's transcript.
SELECT count(*) AS yookr_rows_to_purge,
       count(*) FILTER (
           WHERE NOT EXISTS (
               SELECT 1 FROM readings d
               WHERE d.project = 'spohf-datalake'
                 AND d.device_name = y.device_name
                 AND d.sensor_tag  = y.sensor_tag
                 AND d.time        = y.time)
       ) AS rows_with_no_datalake_counterpart
FROM readings y
WHERE y.project = 'yookr-direct';

-- ---------------------------------------------------------------------------
-- 1. Drop the cagg. It SELECTs `project`, so the column cannot be dropped while
--    it exists. `ensure_aggregates` uses CREATE ... IF NOT EXISTS, so it can
--    never rebuild this itself — the new image recreates it on `source` at boot.
-- ---------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS sensors_daily_summary CASCADE;

-- ---------------------------------------------------------------------------
-- 2. Purge yookr-direct, one month at a time. A single 4.1M-row DELETE on a
--    hypertable builds one enormous transaction; monthly chunks keep each
--    commit bounded and let a failure resume cheaply.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    lo   timestamptz;
    hi   timestamptz;
    gone bigint;
BEGIN
    SELECT date_trunc('month', min(time)), date_trunc('month', max(time)) + interval '1 month'
      INTO lo, hi
      FROM readings WHERE project = 'yookr-direct';

    WHILE lo < hi LOOP
        DELETE FROM readings
        WHERE project = 'yookr-direct'
          AND time >= lo AND time < lo + interval '1 month';
        GET DIAGNOSTICS gone = ROW_COUNT;
        RAISE NOTICE 'purged % rows from %', gone, lo::date;
        lo := lo + interval '1 month';
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 3. Uniqueness pre-check. The 3-column unique index cannot be built if any
--    (device, sensor, time) still has two rows. Manual rows live on their own
--    synthetic devices, so after the purge this must be empty.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    dupes int;
BEGIN
    SELECT count(*) INTO dupes
    FROM (
        SELECT 1 FROM readings
        GROUP BY device_name, sensor_tag, time
        HAVING count(*) > 1
        LIMIT 5
    ) d;

    IF dupes > 0 THEN
        RAISE EXCEPTION
            'ABORT: (device_name, sensor_tag, time) is not unique after the purge. '
            'The dedup index cannot be built. Inspect before dropping the column.';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 4. Swap the dedup index to the 3-column key.
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup_v3
    ON readings (device_name, sensor_tag, time);
DROP INDEX IF EXISTS idx_readings_dedup_v2;
DROP INDEX IF EXISTS idx_readings_dedup;

-- ---------------------------------------------------------------------------
-- 5. Drop the column. From here the OLD image errors on every dashboard query.
-- ---------------------------------------------------------------------------
ALTER TABLE readings DROP COLUMN project;

-- ---------------------------------------------------------------------------
-- 6. Drop the retired sync's metadata row so /status stops reporting it.
-- ---------------------------------------------------------------------------
DELETE FROM sync_metadata WHERE endpoint = 'yookr-direct';

-- ---------------------------------------------------------------------------
-- Post-migration (after the new image is running, which recreates the cagg on
-- `source` WITH NO DATA):
--
--   CALL refresh_continuous_aggregate('sensors_daily_summary', NULL, NULL);
--
-- then rebuild the coverage index — daily_coverage still holds days whose rows
-- were just purged, and it is insert-only:
--
--   POST /rebuild-coverage   (blue /maintenance page)
--
-- then restore `sync.enabled: true`.
-- ---------------------------------------------------------------------------

SELECT count(*) AS readings_remaining FROM readings;
