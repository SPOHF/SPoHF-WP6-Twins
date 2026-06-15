# Make the datalake's real coverage visible: project-aware dedup + clean tag

**Status:** Step 1 ✅ shipped + verified on prod 2026-06-15; Step 2 pending

> **Step 1 done (`759d838`):** project-aware dedup + `spohf-datalake` tag deployed.
> Prod-verified: migration clean (v2 index in, old out, yookr-direct intact at
> 3.65M), datalake & yookr-direct rows now **coexist** at the same timestamps with
> identical values, and `/status` shows the datalake's real coverage (21 series
> fresh — the relay's one-sensor-per-device subset, now visible not absorbed).
> **Step 2 delete ✅ (2026-06-15):** removed 593,761 legacy `project='unknown' AND
> source='unknown'` rows from prod — yookr-direct, spohf-datalake, and manual
> (long_data/insects/fertigation) all intact. `/status` datalake view is now clean
> (fresh spohf-datalake + manual, no stale automated clutter).
> **Deferred:** the full historical backfill under `spohf-datalake` — better done
> *after* SPoHF fixes the relay (issue 024) so it lands all 58 series in one pass
> rather than re-pulling the partial 21. See `docs/blue/spohf-relay-bug-report.md`.

## Design source

Grill/diagnosis in `docs/blue/yookr-direct-retirement.md` (the dedup-race +
tagging analysis) and the prod investigation 2026-06-15. Prerequisite groundwork
for epic **024** (it builds the clean two-bucket tagging the end state needs).

## Problem

`/status` cannot show the SPoHF datalake's true coverage. Both syncs pull the same
yookr sensors at the same `(device, sensor, time)`, and the dedup unique key is
`(device, sensor, time)` with no `project`; the upsert keeps the first writer's
project. yookr-direct inserts first, so the datalake's records are **absorbed** —
value updated, row stays `project='yookr-direct'`. The datalake project owns
nothing recent, so its coverage shows as empty even though the sync runs.

(Separately, the relay is itself incomplete — one sensor per device, issue 024 —
but this change makes that gap *visible and monitorable* rather than hidden.)

## What to build

Let the datalake's rows **coexist** with yookr-direct's under their own tag, kept
in the **toggle dimension (`project`)** — NOT `source` (which carries manual-
provenance "always-visible" semantics and would force a cagg rebuild).

1. **Datalake sync writes `project='spohf-datalake'`** (constant), overriding the
   relay API's `reading.project` (which defaults to `unknown`). yookr-direct keeps
   `project='yookr-direct'`; `source` stays manual-only.
2. **Dedup key → `(device_name, sensor_tag, time, project)`** — the unique index
   and the `upsert_readings` `ON CONFLICT` target. So `spohf-datalake` and
   `yookr-direct` rows for the same instant coexist instead of absorbing. (Manual
   rows are different devices, so `project` alone suffices — no `source` in the key.)
3. **Delete the old datalake rows** `WHERE project='unknown' AND source='unknown'`
   (594k). Safe — manual data carries distinct `source` (`long_data`/`insects`/
   `fertigation_events`), yookr-direct is `project='yookr-direct'`.
4. **Full datalake re-sync** → lands as `spohf-datalake`.

Blue-only: `upsert_readings` is called solely by the two blue orchestrators;
`idx_readings_dedup` is per-twin. Red untouched.

## Incremental execution (prod is a 4.2M-row hypertable)

- **Step 1 (small, reversible):** schema migration (dedup index → +project) + upsert
  `ON CONFLICT` + datalake tag → `spohf-datalake`. Deploy, sync a **short recent
  window**, verify the datalake's series now appear under the datalake view on
  `/status` (coexisting, not absorbed).
- **Step 2:** the 594k `project='unknown' AND source='unknown'` delete + full
  historical backfill.

## Acceptance criteria

- [ ] Dedup unique index is `(device_name, sensor_tag, time, project)`; `upsert_readings`
      `ON CONFLICT` matches; schema migration is idempotent on existing prod
- [ ] Datalake sync writes `project='spohf-datalake'`; yookr-direct still `yookr-direct`
- [ ] Same `(device, sensor, time)` from both sources yields **two coexisting rows**
      (one per project), not one absorbed row — covered by a test
- [ ] After Step 2, `/status` datalake view shows the relay's real coverage (the
      ~21/58 series it delivers), fresh — not empty
- [ ] Manual data (`long_data`/`insects`/`fertigation_events`) untouched by the delete
- [ ] `project` remains trivially droppable in 024 (datalake = only automated source once
      yookr-direct is gone)

## 024 follow-up (not here)

Once SPoHF fixes the relay (024's hard blocker) and the datalake is verified complete:
remove yookr-direct, drop `project`, converge blue to red's source-only model.

## Blocked by

None for Step 1. Step 2's "good coverage" outcome is still gated on the upstream
relay fix (024) — but this issue makes that gap *visible*, which is its point.
