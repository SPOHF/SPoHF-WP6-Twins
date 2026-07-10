# Retiring yookr-direct — exit criteria & sequence

**Status: UNBLOCKED as of 2026-07-10.** Goal: make the SPoHF datalake the single canonical
automated source and remove the `yookr-direct` ingest, the dual-source toggle, and the
`project` column — converging blue on red's single-categorical (`source`) model. See the
coverage snapshot: [`yookr-vs-datalake-coverage.md`](./yookr-vs-datalake-coverage.md).

## ✅ The hard blocker is resolved

The retirement was deferred on 2026-06-15 because the `yookr-data` relay exposed only
**one sensor per device** (21 of yookr-direct's 58 series; `weatherstation:airTemperature`
absent). SPoHF has fixed it. Verified against prod on 2026-07-10:

| exit criterion | status |
|---|---|
| Relay exposes every sensor per device | ✅ **0 yookr-only series** (59 shared, 33 datalake-only, 92 total) |
| The 5 previously-absent devices (`366D`, `366E`, `3670`, `3672`, `PH1 \| 4D1D`) | ✅ present, fresh to today |
| `weatherstation:airTemperature` | ✅ present (50,351 rows), fresh |
| `sync_metadata.yookr-data` healthy, recent, non-zero | ✅ |
| Datalake freshness | ✅ `max(time)` 10:31 UTC vs yookr's 11:25; 3,385 vs 3,507 rows/24 h |

The secondary problems recorded earlier are all closed too: the 401 token revocation
(restored 2026-06-15), the `/status` coverage attribution leak (fixed at day granularity),
GDD's dependency on yookr weather (decoupled to OpenMeteo), and the dedup race (issue 026).

## ⚠️ What retiring yookr-direct actually costs

The datalake is a superset by *series* but not by *rows*: **337,081 yookr-only rows** (8.2%
of yookr-direct's 4.10 M), all within 2024-11 → 2025-12.

- **2024-11 → 2025-11 — thinning.** The relay dropped 3–16% of samples; every series is
  still present every day. Harmless.
- **2025-12 — a hole.** 36 of 59 series have zero datalake rows (56,805 readings). The
  datalake kept exactly one sensor per device that month: December 2025 is the relay bug
  preserved in the data.

Attempt a targeted relay backfill of that window *before* purging. The 2026-06-16 full
backfill already re-pulled it and still got the subset, so the gap is probably in SPoHF's
stored history — in which case the fix is an upstream backfill request, not more syncing.

## The purge: why it is still needed, and why the old reason expired

The previous version of this document justified step 2 ("purge `project='yookr-direct'`")
as *"frees the dedup keys"*: the unique index was `(device_name, sensor_tag, time)` with no
`project`, and `upsert_readings`' `ON CONFLICT … DO UPDATE` rewrote `value` but never
`project`. Whichever source inserted a key first owned it forever, so a datalake resync
could overwrite a row's *value* but never reclaim its *ownership*.

**Issue 026 removed that constraint** by putting `project` into the dedup key
(`idx_readings_dedup_v2` on `(device_name, sensor_tag, time, project)`). The two sources now
coexist as separate rows and the datalake already owns its own data. The purge no longer
makes the datalake canonical — it is already canonical.

What the purge is still needed for is narrower and purely mechanical: **`ALTER TABLE readings
DROP COLUMN project` requires uniqueness on `(device_name, sensor_tag, time)`**, which means
removing one row from every duplicated pair. That is a de-duplication requirement, not a
"delete everything yookr wrote" requirement — a dedupe-merge (drop only rows whose key also
exists under `spohf-datalake`) would satisfy it while preserving the 337 k yookr-only rows.

**Decision (2026-07-10): full purge**, so every surviving automated row provably came from
the datalake. Safe now that no series is yookr-only; the cost is the row deficit above.

## Retirement sequence

`ensure_aggregates` cannot perform this migration: `CAGG_SQL_TEMPLATE` is
`CREATE MATERIALIZED VIEW IF NOT EXISTS`, so changing `project_column` on an existing
database is a **silent no-op**. The cagg must be explicitly dropped and rebuilt.

Ordering is forced by a deploy trap — the **old image crashes on the new schema**
(`CREATE UNIQUE INDEX … (…, project)` on a dropped column) and the **new image crashes on
the old schema** (a 3-column unique index cannot be built while both projects' rows
coexist). So the migration runs *between* the two deploys.

1. Backfill 2024-11 → 2026-01 from the relay; re-audit December 2025.
2. Disable the sync CronJob via `sync.enabled: false` in `helm/shared/values.yaml`
   (a manual `kubectl patch --suspend` is reverted by argocd).
3. Back up: `COPY (SELECT * FROM readings WHERE project='yookr-direct') TO … CSV HEADER`.
4. `DROP MATERIALIZED VIEW sensors_daily_summary CASCADE` (it depends on `project`).
5. Purge `project='yookr-direct'` in monthly batches.
6. Pre-check uniqueness on `(device_name, sensor_tag, time)` — must return zero duplicates.
7. Swap `idx_readings_dedup_v2` → `idx_readings_dedup_v3` on the 3-column key.
8. `ALTER TABLE readings DROP COLUMN project`.
9. Deploy the new image; startup recreates the cagg on `source` `WITH NO DATA`.
10. `CALL refresh_continuous_aggregate('sensors_daily_summary', NULL, NULL)`, rebuild
    `daily_coverage`, re-enable the sync.

Expect a ~2-minute dashboard outage between steps 8 and 9 (the running old image queries a
dropped column). Blue is single-replica by design.

## Code to delete

- `src/wp6_data/sync/yookr_orchestrator.py`, `src/wp6_data/yookr/` (client + sensors).
  ⚠️ **Keep `src/wp6_data/blue/sensor_overview_SPoHF.csv`** — `blue/treatments.py` reads it
  through its own path.
- `src/wp6_data/blue/datasource.py`, `src/wp6_data/blue/yookr.py`, and the `is_yookr` branch
  in `blue/routes/ops.py` (this is issue 029, folded in).
- The second `DataSource` in `blue/dashboard.py`. The shared layer already handles a
  single-source twin: static badge, no toggle, no cookie dispatch.
- `project` filtering throughout `blue/deps.py`; the `--yookr` flag in `__main__.py`; the
  `yookr_*` settings; the `WP6_YOOKR_*` env in `helm/shared/templates/cronjob.yaml`.

## After: what becomes visible

Removing the toggle exposes 33 datalake-only series it was hiding — two dead test rigs
(931 k rows), a 19-series *forecast* feed under the device name
`Grubbenvorst, Limburg, Nederland`, 10 stray rows under a raw IMEI, and the dead `366F` row
sensor. Decide per series: enumerate in `blue/metadata.yaml` or filter out.

Still open upstream: the `0Exx` vs `SPoHF_EC-BV_rijN` device-name duplication — the same
physical soil probes under two names, both now fully populated. See
[`spohf-relay-bug-report.md`](./spohf-relay-bug-report.md).
