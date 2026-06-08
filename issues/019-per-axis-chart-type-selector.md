# Per-Y-axis chart-type selector + URL contract (line only)

**Status:** ready-for-agent

## Design source

ADR `docs/adr/0005-boxplot-distributions-built-client-side-from-raw.md` and the
resolved design for per-Y-axis chart types on the unified `/chart` page.

## What to build

Introduce a **chart type that binds to the Y-axis** on the unified `/chart`
page. Each axis gains a `chartType` setting (`line` | `scatter` | `box`),
selectable from a segmented control in the axis's control block — one selector
in unified mode, one per axis in split mode, matching how aggregation controls
already mirror by axis.

This slice ships the **selector + state plumbing only**. `line` is the only
functional type; `scatter`/`box` are present in the selector but render as line
(or are inert) until their own slices land. The point is the seam: a per-axis
`chartType` in config, a render-mode branch at the trace-build sites, and a
shareable URL contract — with **zero behavior change** for existing charts.

The chart type round-trips through the URL via **`ct`** (left/unified) and
**`ct_r`** (right), following the existing `_r` right-axis convention. Absent →
`line` (so every existing shared link is unchanged); an invalid value falls back
to `line`, mirroring the existing aggregation param validation.

## Acceptance criteria

- [ ] Each axis control block (unified + both split blocks) shows a `[Line | Scatter | Box]` segmented selector, styled consistently with the existing aggregation buttons, defaulting to Line
- [ ] Chart type is held per axis in the axis config and honored via `cfgFor(axis)` like the other per-axis settings
- [ ] `ct` / `ct_r` URL params encode the selection; absent → line; invalid → line; selecting a type updates the URL so the chart is shareable/bookmarkable
- [ ] Split-mode toggle governs chart type the same way it governs aggregation (unified selector drives both axes when split is off)
- [ ] No visual change to any existing chart: a line chart with no `ct` param renders exactly as before
- [ ] A render-mode seam exists at the trace-build sites so scatter/box can branch without restructuring (scatter/box still draw as line in this slice)

## Deferred / out of scope

Scatter rendering (issue 020); boxplot rendering and the box-specific control
behavior — raw fetch, slider relabel, disabled agg/band (issue 021).

## Blocked by

None - can start immediately.
