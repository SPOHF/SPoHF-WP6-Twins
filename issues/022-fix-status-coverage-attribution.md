# Fix /status coverage attribution (honor the source toggle for automated days)

**Status:** ✅ Completed and verified 2026-06-12

## Design source

The grill diagnosis recorded in `docs/blue/yookr-vs-datalake-coverage.md` and
`docs/blue/yookr-direct-retirement.md`. Confirmed against prod (db `postgres` on
`wp6-data-timescaledb`, kube context `old`).

## Problem

The `/status` coverage grid shows automated coverage days that **ignore the active
data source**. Under the "SPoHF Datalake" view it displays `weatherstation:airTemperature`
days right up to today — but those fresh days were written by `yookr-direct`. The
datalake's own last real day for that sensor is 2026-03-20. This masked the
datalake's staleness and made it look healthy when it is not.

Root cause: `daily_coverage` has columns `(device_name, sensor_tag, day, source)` —
**no `project`**. `fetch_daily_coverage` (`src/wp6_data/blue/deps.py`) builds
`visible_auto` as the distinct `(device_name, sensor_tag)` pairs from the
`sensors_daily_summary` cagg under the project filter, then shows **all**
`daily_coverage` days for any visible pair — leaking the other source's days.

## What to build

Tighten the automated-visibility match from pair-level `(device, sensor)` to
**day-level `(device, sensor, day)`** using the cagg, which already buckets by day
and groups by `project`. Join `daily_coverage` to `sensors_daily_summary` on
`(device_name, sensor_tag, day)` under the project filter, so an automated day
shows only when that source actually owns data on that day. Manual coverage
(`source = ANY(manual_sources)`) stays always-visible and source-based, unchanged.

Query-only fix — no cagg/schema change, `daily_coverage` keeps its current columns.

## Acceptance criteria

- [ ] Under the Datalake view, an automated sensor's coverage days reflect only datalake-owned days (`project <> 'yookr-direct'`); under the Yookr view, only `yookr-direct` days. Verified against prod for `weatherstation:airTemperature` (datalake last day ≈ 2026-03-20, not today)
- [ ] Manual sensors (e.g. `insect-trap`) remain visible under both views, unchanged
- [ ] No schema/cagg migration; the fix is in the `fetch_daily_coverage` query only
- [ ] No regression for sensors that are genuinely fresh in the active source
- [ ] Coverage test asserts the per-source day filtering; run the e2e suite (`pytest tests/e2e/ -m e2e`) since this touches the coverage/cagg path

## Out of scope

Fixing the datalake relay itself (upstream); GDD (issue 023).

## Blocked by

None — can start immediately.

## Comments

**2026-06-12 — implemented.** Changed the `visible_auto` CTE in
`fetch_daily_coverage` (`src/wp6_data/blue/deps.py`) to select
`(device_name, sensor_tag, bucket::date AS day)` and match `daily_coverage` on
`(device, sensor, day)` instead of just `(device, sensor)`. Query-only; no schema
change. Regression test added: `tests/e2e/test_blue_coverage_source_filter.py`
(verified it fails on the old pair-level query, passes on the fix).

Validated against prod (`wp6-data-timescaledb`, db `postgres`) for
`weatherstation:airTemperature`: datalake view now reports last day **2026-03-20**
(the real datalake staleness) instead of **2026-06-12** (yookr-direct's leaked
days); yookr view still reports 2026-06-12. Full suite green: 455 unit + 40 e2e,
ruff clean.
