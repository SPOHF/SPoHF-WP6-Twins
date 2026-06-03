# Crop Climate by Height — read-only table view

**Status:** ✅ Completed and verified 2026-06-03

## Design source

Red ADR `src/wp6_data/red/docs/adr/0002-prescriptive-risk-rebuildable-episode-cache.md`
and the **Growth section** / **Height DLI** terms in `src/wp6_data/red/CONTEXT.md`.
No PRD — this feature's design lives in the ADR + glossary.

## What to build

A third view under the existing `/multi_height` hub, at `/multi_height/crop-climate`:
a per-**Growth section** table. Rows are the five growth sections in fixed top-to-bottom
order (H1 "Kop", just above the canopy → H5 "Substraat/wortelzone", root zone), the same
mapping for both wires. Section labels and order come from a new `growth_section`
block (label + order) declared per wire device in red's `metadata.yaml` — enumerated
from metadata, never hardcoded.

One wire at a time via the existing wire pill toggle; a **daily** view with a date
picker (as `single-simple` does). The left column is a simple **placeholder plant SVG
rail** — five zones aligned to the rows, a static asset that can be swapped for nicer
art later. Each row shows the current (latest) PAR value plus sparklines of the four raw
measurement types (PAR / Temp / Hum / CO₂) for the selected day, reusing the
`wire-trends` per-height data path. Cells are tinted **relatively across heights**
(per-column min/max) reusing the existing `value_to_color` helper. No risk judgments yet
— this slice is purely descriptive.

## Acceptance criteria

- [ ] New hub card on `/multi_height` linking to `/multi_height/crop-climate`
- [ ] `growth_section` (label, order) declared in `metadata.yaml`; view enumerates sections from metadata, not hardcoded
- [ ] Rows ordered H1→H5 (top→root); one wire selected via the existing pill; day chosen via date picker
- [ ] Placeholder plant SVG rail renders five row-aligned zones from a swappable asset file
- [ ] Each row shows latest PAR value + per-day sparklines for par/temp/hum/co2 (reusing the wire data path)
- [ ] Cells tinted by relative rank within each column (`value_to_color`, per-column min/max across the five heights)
- [ ] Gated with `verify_session_user`, consistent with the other multi-height views
- [ ] A day with missing/no data renders gracefully (no crash, clear empty state)

## Deferred / out of scope

Botanical illustration (placeholder SVG only), i18n/translations, any risk columns or judgments.

## Blocked by

- None — can start immediately
