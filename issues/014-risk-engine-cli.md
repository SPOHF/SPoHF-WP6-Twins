# Risk engine + `wp6-red-eval-risk` CLI

**Status:** ✅ Completed and verified 2026-06-03 (CLI-validated against prod wire data)

## Design source

Red ADR `src/wp6_data/red/docs/adr/0002-prescriptive-risk-rebuildable-episode-cache.md`
and the **VPD** / **Fungal-risk** / **Height DLI** / **Canopy light deficit** / **Risk episode**
terms in `src/wp6_data/red/CONTEXT.md`.

## What to build

A pure, side-effect-free **risk engine** computing the derived metrics per **Growth
section** from wire readings:

- **Height DLI** — the day's integral of PAR measured at one height (the per-height
  integral the multi-height views already compute).
- **VPD** — derived from temperature + humidity at the same height.
- **Fungal-risk (wet-hours)** — a rolling accumulation of how long RH at a height has
  stayed above a high-RH threshold within a trailing window.
- **Canopy light deficit** — H1's Height DLI vs a configured tomato DLI target,
  evaluated for **H1 only** (lower sections need the not-yet-known light-penetration
  relationship, per the ADR/CONTEXT).

Plus **risk-episode detection**: contiguous spans where a metric stays above its active
threshold, with a configured **minimum duration** to suppress flapping. Signature:
`(readings, thresholds) → (current_state per section, episodes)`. All thresholds,
targets, the VPD band, the trailing window, and the min-duration live in
`metadata.yaml` — no hardcoded constants.

A console-script entrypoint **`wp6-red-eval-risk`** runs the engine over a date range +
wire against the (forever-retained) wire data and **prints** current state + episodes.
It is read-only — runnable locally and against prod to validate thresholds *before* any
persistence exists. Note the wet-hours accumulator's lookback must extend *before* the
displayed range to be correct at the range start.

## Acceptance criteria

- [ ] Pure functions for Height DLI, VPD, Fungal-risk wet-hours, and Canopy deficit; engine performs no I/O
- [ ] Risk-episode detection with config min-duration; each episode carries section, risk, start, end, peak, and the threshold-set used
- [ ] All thresholds/targets/window/band/min-duration read from `metadata.yaml`
- [ ] Canopy deficit evaluated for H1 only
- [ ] `wp6-red-eval-risk` console script registered in `pyproject.toml`; accepts a date range + wire; prints state + episodes
- [ ] CLI runs against prod wire data read-only (writes nothing)
- [ ] Unit tests use source constants (no magic numbers): wet-hours accumulation incl. gap clipping, VPD band crossing, episode min-duration de-flap, canopy deficit at/under/over target

## Deferred / out of scope

Persistence (issue 015), any UI, light-penetration judgments for H2–H5.

## Blocked by

- None — can start immediately
