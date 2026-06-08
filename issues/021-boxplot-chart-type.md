# Boxplot chart type (client-side from raw)

**Status:** ready-for-agent

## Design source

ADR `docs/adr/0005-boxplot-distributions-built-client-side-from-raw.md` and the
resolved design for per-Y-axis chart types on the unified `/chart` page.

## What to build

Make the **boxplot** chart type functional on an axis. Per ADR 0005, a box's
distribution is built **client-side from raw points**, not from server-side
quantiles. When an axis is in box mode:

- It fetches **raw** points (`bkt=0`) regardless of the aggregation buttons.
- The aggregation **func** (avg/min/max/sum) is **ignored** — only the bucket
  slider matters. The slider becomes a client-side **"box width"** control: each
  raw point is floored to its bucket start in the browser (on the API's
  local-ISO times) and identical bucket-x values collapse into one box, which
  Plotly draws with computed quartiles.
- **One box-series per sensor** (no same-label pooling), drawn side-by-side via
  `boxmode: 'group'`, each keeping its own color.
- All boxes share the same real **datetime** x-axis as line/scatter, so
  switching types doesn't shift the axis.

Control-panel behavior for a box axis: the aggregation button row is **disabled
with a hint** (func is ignored); the bucket slider is **always enabled** and
relabeled **"Box width"** (decoupled from the agg-enabled state); the range-band
toggle is **disabled**. The existing `.truncation-warning` is reused as-is — a
box rides the raw fetch path, so a clipped distribution already trips it.

## Acceptance criteria

- [ ] An axis set to Box renders one box per sensor per bucket, grouped side-by-side, on the shared datetime axis
- [ ] Box mode fetches raw data and ignores the aggregation func; changing the agg buttons does not change the boxes
- [ ] The bucket slider controls box width; it is enabled in box mode even when aggregation is "off", and is labeled accordingly
- [ ] Aggregation buttons and the range-band toggle are disabled (with a hint) while box is selected
- [ ] A truncated raw fetch in box mode surfaces the existing truncation warning
- [ ] Split mode can mix box on one axis with line/scatter on the other
- [ ] `ct=box` / `ct_r=box` round-trips through the URL

## Deferred / out of scope

Server-side quantile push-down (the ADR's escape hatch for long-range
boxplots); same-label distribution pooling; box-specific styling beyond Plotly
defaults.

## Blocked by

- `issues/019-per-axis-chart-type-selector.md`
