# Retiring yookr-direct — what happened, and why

**Status: ✅ DONE — migrated on prod 2026-07-10.** The SPoHF datalake is now the single
canonical automated source. The `yookr-direct` ingest, the dual-source toggle and the
`readings.project` column are gone; blue matches red's single-categorical (`source`)
model. Coverage snapshot: [`yookr-vs-datalake-coverage.md`](./yookr-vs-datalake-coverage.md).

## Outcome

| | before | after |
|---|--:|--:|
| `readings` rows | 9,032,000 (2 projects + manual) | **5,328,472** (datalake + manual) |
| automated series | 59 direct / 92 relayed | **92** |
| dedup key | `(device, sensor, time, project)` | `(device, sensor, time)` |
| cagg groups by | `project` | `source` |
| `daily_coverage` rows | 44,930 | **40,607** (stale days pruned) |

Before purging, a truncation bug in our own client was fixed and the affected window
re-synced, cutting the yookr-only rows from **337,081 → 59,493** — so the purge cost only
December 2025 (see below) plus ~660 stragglers, instead of 337k readings.

A CSV of every purged `yookr-direct` row was taken first (4,104,095 rows, 491 MB).

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

## ⚠️ The "missing" rows were mostly our own bug

The datalake was a superset by *series* but not by *rows*: **337,081 yookr-only rows** (8.2%
of yookr-direct's 4.10 M), all within 2024-11 → 2025-12. Investigating that window turned up
two different causes.

**~280,000 rows: we were truncating.** The relay is Elasticsearch-backed and refuses
`from + size > max_result_window` (10,000). `SpoHFClient.fetch_window` paged by offset until
a short page, so once a day held more than 10,000 records the relay returned empty and we
read that as "no more data". The two `Natte bol` test rigs (931k rows) ran **2024-11-15 →
2025-12-31** and pushed daily volume over the cap for *exactly* the deficit window.

`fetch_window` now bisects an overflowing window until each half fits. Re-syncing
2024-11-01 → 2025-12-01 with the fixed client recovered the rows: **330 of 396 days (83%)
needed a split**. Yookr-only rows fell **337,081 → 59,493**.

Because bisection re-fetches, and the relay's offset pagination returns duplicates of its
own, ingest must be idempotent — hence the `ON CONFLICT DO UPDATE` and its e2e test.

**58,826 rows: December 2025 is genuinely gone.** The relay still serves one sensor per
device for that month — verified by querying the endpoint directly (a Dec-2025 day returns
22 devices / 22 series / **0** devices with >1 sensor, while neighbouring months return 60
series across 18 multi-sensor devices). Its *stored* history was never repaired, so no
re-sync can recover it. yookr-direct held the only complete copy, and the purge destroyed
it. Backfill requested upstream: [`spohf-relay-bug-report.md`](./spohf-relay-bug-report.md),
ask (a). The remaining ~660 rows are scattered singletons the relay never received.

> **`/status` could not have caught any of this.** `fetch_daily_coverage` matches the cagg at
> `(device, sensor, day)` — a day counts as covered if the series has ≥1 row. Losing the tail
> of every day is invisible at that granularity. Only a row-level anti-join sees it.

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

## Retirement sequence (as executed, 2026-07-10)

`ensure_aggregates` cannot perform this migration: `CAGG_SQL_TEMPLATE` is
`CREATE MATERIALIZED VIEW IF NOT EXISTS`, so changing `project_column` on an existing
database is a **silent no-op**. The cagg must be explicitly dropped and rebuilt.

Ordering is forced by a deploy trap. The **old image breaks on the new schema** (it SELECTs
`project`), and the **new image refuses to boot on the old schema** — `ensure_schema_blue`
raises `UnmigratedSchemaError`, because its 3-column unique index cannot be built while both
projects' rows coexist. So the migration runs *between* the two deploys, and the guard makes
that safe: a premature deploy crash-loops with an actionable message instead of corrupting
anything.

1. Fix the truncation bug; backfill 2024-11-01 → 2025-12-01; re-audit.
2. `COPY (SELECT * FROM readings WHERE project='yookr-direct') TO STDOUT CSV HEADER` → local
   file. Verify the row count. **This is the only way back.**
3. Push `sync.enabled: false` (a manual `kubectl patch --suspend` is reverted by argocd).
   The old image's flagless entrypoint also ran the yookr sync, which would otherwise
   re-insert rows behind the purge.
4. Run [`scripts/migrate_blue_drop_project.sql`](../../scripts/migrate_blue_drop_project.sql):
   orphan-series guard → drop cagg → monthly purge → uniqueness pre-check → index swap →
   `DROP COLUMN project` → drop the `yookr-direct` `sync_metadata` row.
5. The new pod clears its boot guard and recreates the cagg on `source` `WITH NO DATA`.
6. `CALL refresh_continuous_aggregate('sensors_daily_summary', NULL, NULL)` and rebuild
   `daily_coverage` (it is insert-only, so it still claimed the purged days).
7. Push `sync.enabled: true`.

Blue is single-replica by design; the rolling update kept the old pod serving until the new
one passed its guard, so the outage spanned the migration itself (~35 min, dominated by the
purge and the unique-index build).

### Two traps, if you ever run something like this again

- **Killing `psql` does not stop the server.** Terminating the local `kubectl exec` client
  leaves the backend running its current statement. The migration ran to completion after the
  client was killed. Check `pg_stat_activity` before assuming an abort worked.
- **`count(*) FILTER (WHERE NOT EXISTS (...))` is not an anti-join.** It defeats the planner's
  rewrite and re-runs the subquery per row: 14+ minutes on 4.1M rows, versus seconds for the
  same predicate in a `WHERE` clause. Likewise, a `DO $$ … $$` block is *one statement* — the
  monthly `DELETE` loop needs an explicit `COMMIT` or it is still one giant transaction. Both
  are fixed in the script.

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
