# Rebuildable risk-episode cache + admin Update/Rebuild

**Status:** ✅ Completed and verified 2026-06-03 (store e2e-validated against wp6_red)

## Design source

Red ADR `src/wp6_data/red/docs/adr/0002-prescriptive-risk-rebuildable-episode-cache.md`
and the **Risk episode** term in `src/wp6_data/red/CONTEXT.md`.

## What to build

Red's first **view-authored write path**: a **rebuildable cache** table in red's
TimescaleDB holding **risk episodes** plus the latest per-section state, each row stamped
with the **threshold-set** it was computed under. Two admin-gated
(`verify_session_admin`) actions invoke the issue-014 engine:

- **Rebuild** — recompute a *selectable date range* from raw wire data, replacing the
  episodes in that range (used after retuning thresholds).
- **Update** — incremental: extend the log up to now from last-known state (the manual
  stand-in for a future scheduled job).

The `/multi_height/crop-climate` page reads the last-built per-section verdict, shown as
*"as of the last Update/Rebuild"*. Follow the existing derived-table pattern
(`sensors_daily_summary` cagg / `daily_coverage`) and bootstrap schema idempotently
alongside `ensure_schema_red`. No scheduler in this slice.

## Acceptance criteria

- [ ] Cache table (episodes + current per-section state) created idempotently in red's TSDB, threshold-set stamped per row
- [ ] Admin-gated **Rebuild(range)** and **Update(incremental)** actions call the pure engine and write the cache
- [ ] Rebuild replaces only the selected range; Update appends/extends from last-known state to now
- [ ] Button disabled while a build runs (no locking infra); repeated presses are safe (last-write-wins)
- [ ] crop-climate page reads and displays the persisted per-section verdict, labelled with the last build time
- [ ] Reproducible: re-running Rebuild over the same range + thresholds yields identical episodes
- [ ] Tests cover write/read roundtrip and range-replace semantics
- [ ] e2e run for the schema/write path (`pytest tests/e2e/ -m e2e`) before merge

## Deferred / out of scope

Auto-refresh CronJob (the Update button is its manual stand-in); immutable append-only audit (the cache is rebuildable by design).

## Blocked by

- `issues/014-risk-engine-cli.md`
