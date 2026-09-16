# Model quality is scored in physical units, not risk episodes

## Status

accepted

## Context

The climate model (`red/climate/`) predicts per-height temperature, humidity,
CO₂ and PAR on the multi-height wires. `red/risk/engine.py: evaluate(df,
sections, thresholds, tz)` is pure and takes exactly the tidy `height,
measurement, time, value` frame the model produces, so feeding predictions
through the risk engine and scoring the resulting episodes was available for
nothing — and is the more directly useful framing, since "H2 crosses the fungal
threshold in 18 h" is what a grower would act on.

Against that:

- **`risk_thresholds` in `metadata.yaml` is marked PROVISIONAL** — the fungal RH
  cutoff and window, the VPD band, the canopy DLI target, the CO₂ floor and the
  episode minimum duration are horticultural judgement awaiting confirmation,
  not measurements. ADR 0002 records the same caveat.
- **The wires that would validate them were not measuring the greenhouse.**
  `docs/red/wire-data-coverage.md` dates a 46-day window (2026-05-28 →
  2026-07-12) where the greenhouse-level sensors flatlined and the wires read
  outdoor-like values, and the wires' usable record begins only 2026-07-13.
- The project owner stated directly that the current risk readings should not be
  banked on yet.

A score expressed in episodes inherits every one of those thresholds. A model
could be excellent and score badly because a threshold sits in the wrong place,
or poor and score well because a threshold is never crossed — and neither
outcome would be separable from the other.

## Decision

**Model quality is measured in °C, %RH, ppm and µmol/m²/s**, against
baselines in those same units (persistence, climatology, and reference-as-is for
the per-height link), plus a gradient score on the H1→H5 profile shape.

The risk engine stays available as a downstream consumer and is **not** part of
any acceptance criterion. When a risk overlay on the forecast is built, it is
presented as explicitly provisional.

## Consequences

- Scores remain valid when the thresholds change. Retuning `risk_thresholds`
  requires no retraining and invalidates no reported number.
- The two concerns can be debugged separately: a wrong prediction is a model
  problem, a wrong episode from a right prediction is a threshold problem.
- The status page is further from what a grower reads. `/climate/model` reports
  RMSE and skill per target and horizon, not "H2 goes fungal-risky tonight".
  That gap is deliberate for now and closes when the thresholds are worth
  trusting.
- Nothing prevents the overlay later: because the model emits the same frame
  shape `multi_height/data.load_wire_readings` returns, `evaluate` will accept
  predictions unchanged.

## Revisit when

Representative wire data exists across a full season **and** the thresholds have
been tuned against it. At that point predicted-versus-observed episodes become a
meaningful second scoring axis — added alongside the physical-unit scores, not
in place of them.
