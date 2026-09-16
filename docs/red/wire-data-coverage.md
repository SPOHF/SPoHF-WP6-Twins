# Red sensor coverage: what is actually usable for modelling

**Probed 2026-09-16**, read-only against red's MySQL. Stage A of the wire-level
climate prediction work. Everything below is measured, not recalled.

## Headline

Two separate problems, not one:

1. **A 46-day flat regime, 2026-05-28 → 2026-07-12, affects the
   greenhouse-level sensors as well as the wires.** This is wider than the
   "wires were outside for testing" story — `s2101` and `s2103` flatline
   together over exactly the same window.
2. **The wires are not interchangeable.** Only `WS_01_02` reports a complete
   per-height climate. `WS_01_03` has lost temp/hum/CO₂ entirely; `WS_01_01` has
   lost PAR at every height except H5.

## The flat regime

Daily temperature range on both greenhouse-level sensors, °C:

| date | s2101 ΔT | s2103 ΔT | regime |
|---|---|---|---|
| … 2026-05-27 | 27.0 | 17.0 | normal |
| 2026-05-28 | 0.4 | 0.7 | **flat** |
| 2026-06-29 | 0.8 | 0.5 | **flat** |
| 2026-07-12 | 0.3 | 0.2 | **flat** |
| 2026-07-13 | 24.5 | 18.9 | normal |

Boundaries are sharp to the day. The sensors are **not stuck** — 20–90 distinct
values per day — they are reading a genuinely near-constant environment, around
0.2–1.5 °C of daily swing where every other month shows 6–30 °C.

The window spans the declared end of the `2026 spring` crop cycle (2026-06-29,
`metadata.yaml`, marked PROVISIONAL), so a changeover with an empty, idle house
is the natural reading — but that is inference, not evidence. **Needs
confirming with the greenhouse.**

Over the same window the wires read outdoor-like values: `WS_01_02` sat at
+1.2 to +2.8 °C of the outdoor station while running −2 to −6 °C against the
greenhouse, with outdoor-sized diurnal swings. `WS_01_01` showed a different
signature again — under 2 °C of daily range while the house swung 33 °C, which
is a bench, not a greenhouse and not outdoors.

`s1000` (outdoor) also under-reports in June: 2,911 readings against 6,000–8,500
in neighbouring months.

## Wire coverage

| wire | first row | usable from | temp / hum / CO₂ | PAR |
|---|---|---|---|---|
| `WS_01_01` | 2026-05-26 | 2026-07-16 | H1–H5 | **H5 only** (H1–H4 dead since August) |
| `WS_01_02` | 2026-06-03 | 2026-07-13 | H1–H5 | H1–H5 — the only complete wire |
| `WS_01_03` | 2026-07-06 | 2026-07-13 | **none** (dead since August) | H1, H2, H3, H5 |

`rad` (virtual height 0) stops everywhere in early July 2026, consistent with
the 2026-07-02 already recorded in `red/CONTEXT.md`. It was only ever populated
on `WS_01_01` and `WS_01_02`.

## What this leaves for training

| link | span | notes |
|---|---|---|
| Links 1–2 (weather → greenhouse level) | 2025-10-08 → 2026-05-27 and 2026-07-13 → 2026-09-16 | ≈ 9.7 months usable, covers a full seasonal cycle |
| Link 3 (greenhouse level → per height) | **2026-07-13 → 2026-09-16** | ≈ 9.5 weeks, **summer only** |

Link 3 therefore has no winter data at all. A day-of-year feature there would
extrapolate blindly, and no amount of held-out scoring inside summer will reveal
it. Any gradient model fitted now is summer-calibrated and must be revalidated
when a winter of wire data exists.

## Reference sensor choice is not obvious

`s2101` and `s2103` are both greenhouse-level temp/hum, and they behave
differently. Mean daily range, °C:

| month | s2101 | s2103 |
|---|---|---|
| 2025-12 | 23.8 | 11.4 |
| 2026-01 | 26.9 | 12.2 |
| 2026-03 | 30.0 | 14.8 |
| 2026-08 | 23.2 | 18.5 |

`s2101` reaches daily maxima above 50 °C, which points at direct sun rather than
representative air temperature. `crop_cycles.climate.metrics` currently uses
`s2101` for temp/hum and `s2103` for CO₂. For a *reference* that per-height
deviations are measured against, `s2103` looks the steadier choice — **open
decision.**

## Also noticed

`s2100-10-par` … `s2100-14-par` are reporting again from 2026-04-07 (≈10,000 rows
each). `red/CONTEXT.md` and ADR 0001 describe the `s2100-10..15` sensors as
retired and gone. Not relevant to this work, but the documentation and the
database disagree.
