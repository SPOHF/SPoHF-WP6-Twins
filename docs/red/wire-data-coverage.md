# Red sensor coverage: what is actually usable for modelling

**Probed 2026-09-16**, read-only against red's MySQL. Stage A of the wire-level
climate prediction work. Everything below is measured, not recalled.

> **Correction (2026-10-07): the "broken wires" below were a mislabelling, not
> sensor failure.** Only two wires were installed, `WS_01_02` and `WS_01_03`.
> Upstream's `wire_sensor_map` filed `WS_01_03`'s climate sensors and its H4 PAR
> sensor under a `WS_01_01` that was never installed. See
> [The sensor-to-wire mix-up](#the-sensor-to-wire-mix-up). The wire coverage
> table is kept as it was measured, but read it through that section.

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

## The sensor-to-wire mix-up

**Found 2026-09-30, upstream map corrected 2026-10-02.** Each Modbus sensor is a
stable identity, and its readings are its own. What was wrong is which wire each
sensor was filed under. `server_name` encodes the *intended* wire (`par1x` and
`co2comb1x` for wire 1, `par2x` and `co2comb2x` for wire 3, unsuffixed for wire
2). During installation, wire 1's sensors went onto wire 3, and wire 1 was never
put up. `wire_sensor_map` followed the names, not the installation.

| Modbus server | named | filed under (until 2026-10-02) | physically on |
|---|---|---|---|
| 55–59 | co2comb11–15 | `WS_01_01` positions 1–5 | **`WS_01_03`** positions 1–5 |
| 15 | par15 | `WS_01_01` position **5** | **`WS_01_03` position 4** |
| 50, 3–6 | radioation11, par11–14 | `WS_01_01` | not installed |
| 21, 65–69 | par24, co2comb21–25 | `WS_01_03` | not installed |

The mix-up starts on **2026-07-13**, the day the wires came in from outdoor
testing (2026-07-06 → 07-09, when all three reported everything). The ingest
picked up the corrected map at **2026-10-02 07:12** for PAR.

**Since the fix, the combo sensors 55–59 are not written anywhere** (last row
2026-10-02 07:17, still true 2026-10-07). PAR moved over to `WS_01_03` correctly,
so the ingest resolves combo sensors differently from PAR. This is open
upstream.

### What the platform does

`wire_sensor_map` is now the source of truth for which wires exist (`red/wires.py`).
A wire with no `active` sensor is not installed, so `WS_01_01` has disappeared from
every view, export and fit, even though `wire_sensors` still holds its rows and
receives an all-NULL row every poll. Which heights a wire reports is no longer
declared at all. A height the wire never filled has no readings, and the
climate model fits only what had readings.

### The history is still misfiled

`wire_sensors` stores values by *(wire, column)*, not by sensor, and the map keeps
no history. So the map in force at ingest is the only way to tell which sensor
a stored value came from. Rows from 2026-07-13 → 2026-10-02 07:17 still carry the
old labels: `WS_01_01`'s 23,222 rows hold `WS_01_03`'s climate (columns as-is)
and its H4 PAR (in `par5`). Until upstream relabels them, that is the only
climate history `WS_01_03` has, and the platform ignores it.

The map as it stood before the fix (read 2026-09-30; upstream has since
overwritten it, including the `WS_01_01` server ids):

| id | device_id | server_id | server_name | position | active |
|---|---|---|---|---|---|
| 1 | WS_01_01 | 50 | radioation11 | 1 | 1 |
| 2 | WS_01_01 | 3 | par11 | 1 | 1 |
| 3 | WS_01_01 | 55 | co2comb11 | 1 | 1 |
| 4 | WS_01_01 | 4 | par12 | 2 | 1 |
| 5 | WS_01_01 | 56 | co2comb12 | 2 | 1 |
| 6 | WS_01_01 | 5 | par13 | 3 | 1 |
| 7 | WS_01_01 | 57 | co2comb13 | 3 | 1 |
| 8 | WS_01_01 | 6 | par14 | 4 | 1 |
| 9 | WS_01_01 | 58 | co2comb14 | 4 | 1 |
| 10 | WS_01_01 | 15 | par15 | 5 | 1 |
| 11 | WS_01_01 | 59 | co2comb15 | 5 | 1 |
| 12 | WS_01_02 | 40 | radiation1 | 1 | 1 |
| 13 | WS_01_02 | 10 | par1 | 1 | 1 |
| 14 | WS_01_02 | 45 | co2comb1 | 1 | 1 |
| 15 | WS_01_02 | 11 | par2 | 2 | 1 |
| 16 | WS_01_02 | 46 | co2comb2 | 2 | 1 |
| 17 | WS_01_02 | 12 | par3 | 3 | 1 |
| 18 | WS_01_02 | 47 | co2comb3 | 3 | 1 |
| 19 | WS_01_02 | 1 | par1 *(sic; position 4)* | 4 | 1 |
| 20 | WS_01_02 | 48 | co2comb4 | 4 | 1 |
| 21 | WS_01_02 | 2 | par5 | 5 | 1 |
| 22 | WS_01_02 | 49 | co2comb5 | 5 | 1 |
| 23 | WS_01_03 | 60 | radiation1 | 1 | 1 |
| 24 | WS_01_03 | 8 | par21 | 1 | 1 |
| 25 | WS_01_03 | 65 | co2comb21 | 1 | 1 |
| 26 | WS_01_03 | 9 | par22 | 2 | 1 |
| 27 | WS_01_03 | 66 | co2comb22 | 2 | 1 |
| 28 | WS_01_03 | 20 | par23 | 3 | 1 |
| 29 | WS_01_03 | 67 | co2comb23 | 3 | 1 |
| 30 | WS_01_03 | 21 | par24 | 4 | 1 |
| 31 | WS_01_03 | 68 | co2comb24 | 4 | 1 |
| 32 | WS_01_03 | 22 | par25 | 5 | 1 |
| 33 | WS_01_03 | 69 | co2comb25 | 5 | 1 |
