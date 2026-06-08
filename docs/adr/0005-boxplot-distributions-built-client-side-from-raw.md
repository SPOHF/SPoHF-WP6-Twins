# Boxplot distributions are built client-side from raw points

The unified `/chart` page gains per-Y-axis chart types (line/scatter/box). A
box needs a *distribution* per time bucket (≥ Q1/median/Q3), but the server's
bucketed contract (`BUCKETED_COLUMNS`) collapses each bucket to a single
`value` + raw min/max + count — not enough to draw a box. Rather than widen
that contract with percentile columns, an axis in **box** mode fetches **raw**
points (`bkt=0`), floors each point's timestamp to its bucket start **in the
browser**, and hands the raw `y` arrays to Plotly, which computes the quartiles.
Consequently the bucket slider becomes a pure client-side "box width" control
and the aggregate **func** (avg/min/max/sum) is ignored for boxplots — only the
slider matters.

## Considered Options

- **Server-side quantiles** (add `q1/median/q3` to the bucketed output) —
  rejected for v1: it widens a shared contract for one chart type and must be
  implemented in **both** bucketing legs, including the TimescaleDB SQL
  push-down where **MySQL has no percentile aggregate**. Kept as the documented
  escape hatch if long-range boxplots become important.
- **Degenerate box from existing min/max/mean** — rejected: a box without true
  quartiles (and with mean drawn as the median) would silently misrepresent the
  distribution.

## Consequences

- Boxplot logic lives entirely in the chart layer (`UNIFIED_CHART_JS`); no
  twin, provider, or DB-contract changes.
- The raw fetch is capped (`chart_query_limit`, default 10000), so a box over a
  long/dense range is computed from a **truncated** distribution. This trips the
  existing `.truncation-warning` automatically (box rides the raw fetch path),
  so a clipped box is flagged rather than silent — but the warning's stakes are
  higher for a box (biased quartiles) than for a line (fewer points).
- Client-side flooring uses the API's local-ISO times to match the server's
  local-wall-clock bucketing. The two DST-transition buckets per year inherit
  the same accepted approximation already documented for the pandas leg
  (`aggregation.py`), rather than introducing a new one.
