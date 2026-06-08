# Scatter chart type (orthogonal render mode)

**Status:** ready-for-agent

## Design source

ADR `docs/adr/0005-boxplot-distributions-built-client-side-from-raw.md` and the
resolved design for per-Y-axis chart types on the unified `/chart` page.

## What to build

Make the **scatter** chart type functional on an axis. Scatter is purely a
render mode — it draws the same points the line chart would, as markers instead
of a connected line. It is **orthogonal to aggregation**: an axis set to scatter
still obeys whatever aggregation/bucketing the axis has (agg off → raw markers,
the classic scatter; agg on → markers on the bucketed points, with the range
band still available). Only the Plotly draw mode changes.

Concretely: at the trace-build seam from issue 019, when the axis chart type is
scatter, emit markers rather than lines, at **both** the non-aggregated and
aggregated trace branches. Everything else — same-label recombination, the
range band, colors, the right-axis dashing concept — is untouched.

## Acceptance criteria

- [ ] An axis set to Scatter renders its series as markers (points), not connected lines
- [ ] Scatter works with aggregation OFF (raw markers) and ON (markers on bucketed points)
- [ ] The range band still renders for an aggregated scatter axis when the band is enabled
- [ ] Same-label series recombination behaves identically to line mode
- [ ] Left/right split mode can mix line on one axis and scatter on the other
- [ ] `ct=scatter` / `ct_r=scatter` round-trips through the URL

## Deferred / out of scope

Boxplot (issue 021). Any scatter-specific styling beyond the default marker
(e.g. marker size/shape controls).

## Blocked by

- `issues/019-per-axis-chart-type-selector.md`
