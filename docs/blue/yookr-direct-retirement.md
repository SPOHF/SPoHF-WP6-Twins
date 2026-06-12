# Retiring yookr-direct — blockers & exit criteria

**Status: deferred (as of 2026-06-12).** Goal: make the SPoHF datalake the single
canonical automated source and remove the `yookr-direct` ingest + the dual-source
toggle + the `project` column. Blocked today because the datalake is not yet a
healthy superset of `yookr-direct`. See the coverage snapshot:
[`yookr-vs-datalake-coverage.md`](./yookr-vs-datalake-coverage.md).

## Why it's deferred (the problems)

1. **The datalake relay sync is failing.** `sync_metadata.yookr-data`:
   `last_run_success = false`, **316 total failures**, 0 records last run. The
   `yookr-direct` sync is green by contrast.
2. **The datalake is stale across every automated sensor.** Newest automated
   datalake point is 2026-05-12; most are 2025-12-31 → 2026-03-20. `yookr-direct`
   is fresh to today for all of them.
3. **Five automated devices are entirely absent from the datalake** (`366D`,
   `366E`, `3670`, `3672` row sensors; `PH1 | 4D1D` soil-pH). One device
   (`366F`) exists *only* in the datalake and is itself ~a year stale.
4. **The dedup race makes a naive resync ineffective.** `readings`' unique key is
   `(device_name, sensor_tag, time)` — no `project` — and the upsert's
   `ON CONFLICT … DO UPDATE` rewrites `value`/`raw_value` but **never `project`**.
   So any key first inserted by `yookr-direct` stays `project='yookr-direct'`
   forever; a datalake resync overwrites its *value* but can't reclaim ownership.
   ⇒ retirement must be ordered: **stop yookr-direct → purge `project='yookr-direct'`
   rows (frees the keys) → resync/let the datalake re-own them.**
5. **`project` can only be dropped once there's a single ingest.** While both syncs
   write the shared table, `project` is the only thing distinguishing them, and the
   dedup race persists. So "drop the `project` column" is a *consequence* of
   retiring `yookr-direct`, not an independent step. (Blue would then mirror red's
   single-categorical model.)

## Already handled (so they're NOT blockers)

- **GDD's dependency on `yookr-direct` weather** — removed by decoupling GDD to
  OpenMeteo modeled weather at the farm location (separate work). GDD no longer
  reads `readings` for temperature, so it survives yookr-direct removal.
- **`/status` masking the staleness** — the coverage grid showed the datalake as
  healthy because `daily_coverage` has no `project` column, so it leaked
  yookr-direct's fresh days into the datalake view. Fixed separately (cagg join at
  day granularity).

## Exit criteria — retire only when ALL hold

- [ ] `sync_metadata.yookr-data` shows `last_run_success = true` with recent,
      non-zero records over several consecutive runs.
- [ ] Re-running the coverage query (below) shows **every** automated
      `(device, sensor)` fresh (last day ≈ today) under the datalake filter
      (`project <> 'yookr-direct'`), with **no missing devices**.

```sql
SELECT device_name, sensor_tag,
  max(time) FILTER (WHERE project <> 'yookr-direct')::date AS dl_last
FROM readings GROUP BY device_name, sensor_tag
ORDER BY dl_last NULLS FIRST;   -- NULL/old rows at top = still-missing/stale
```

## Retirement sequence (once exit criteria met)

1. Stop the `yookr-direct` sync (cronjob).
2. Purge `project = 'yookr-direct'` rows (frees the dedup keys).
3. Resync / let the datalake re-own the keys; re-verify coverage.
4. Collapse the dashboard to a single datalake source; remove the toggle,
   `datasource.py`, `yookr.py`, and the `is_yookr` branch in `ops.py`.
5. Drop the `project` column (blue → single-categorical, like red).
6. Delete `sync/yookr_orchestrator.py`, `yookr/` client, and related config.
