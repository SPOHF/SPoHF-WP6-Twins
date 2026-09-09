# Cycles and cohorts are a shared model; lane generation stays twin-side

## Status

accepted

## Context

Red needed to connect a fruit measurement to the climate the fruit experienced
while it developed. Tomatoes set a truss every week and ripen over about eight
weeks, so roughly eight overlapping **cohorts** are in flight at any moment —
nothing in the platform expressed that. Blue frames its data yearly, but that
"cycle" is not an entity either: it is a calendar-year slice recomputed per
request in `blue/routes/gdd.py`.

The first draft put the whole feature under `red/crop_cycles/`. Reviewing it
against the maintainability rule ("prefer shared functionality over
duplicated/similar code") showed that most of it was not red's: strip the domain
words away and what remains — *a dated span carrying an outcome, over a shared
calendar* — names no crop at all.

## Decision

Split along what actually needs domain words.

**`shared/cycles.py` and `shared/waterfall.py`** own the vocabulary
(`CycleSpec`, `CohortSpec`, `Cohort`, `Lane`, `Marker`), the attachment rule,
the exposure/coverage arithmetic, and the chart. Both are twin-agnostic by
contract; a grep for twin terms over the two files is part of the verification
steps.

**Twins own lane generation.** Red converts its declared rhythm into a
`CohortSpec` and generates weekly cohorts. Any *additional* dimension is the
twin's fan-out: a twin wanting "cohort per treatment per year" calls
`generate_cohorts` once per treatment and tags each `Lane.group`, rather than
the shared generator growing a second axis.

**A cohort is an undivided span.** The first version subdivided it into named
developmental stages (flowering / fruit set / ripening) bound to red's growth
sections, and `CohortSpec` carried two validated modes to date them — fixed
offsets, or a `resolve_phases` callable for data-dependent boundaries such as
blue's GDD threshold crossings. Both were removed. Red's boundaries were fixed
offsets from the set date, so they encoded nothing the start date did not
already encode, and they consumed the chart's one colour axis to restate a
schedule the reader already knows.

**The daily series is projected onto the lanes** rather than drawn as a strip
above them. The colour axis freed by dropping stages now carries the conditions
each cohort actually lived through, which is the question the module exists to
answer. Two consequences follow: coverage is shown by gaps in the bar instead of
by fading (dimming a bar that encodes a value by colour would corrupt the
reading), and days outside every cohort are not drawn at all.

**Cohorts are derived per request, not persisted.**

## Considered Options

- **Keep everything in `red/`, promote later** — rejected: a second twin
  plausibly wanting the same shape is exactly when an abstraction is paid for,
  and the shared part needed no red words to express.
- **Also share cohort *generation* for every dimension** — rejected: it would
  need a strategy parameter for the treatment/variety axis, to save each twin a
  `for` loop.
- **Keep the developmental stages, uncoloured** — rejected: retained on hover
  for one iteration, then dropped. If a fixed offset from the start date is
  worth showing, it is worth showing as a date, and the reader already has the
  start date on the axis.
- **Keep the climate strip alongside the projection** — rejected: the same
  series twice, costing vertical space on a chart that is already ~1,100px for
  two seasons.
- **Persist cohorts in a table, like `risk_episodes`** — rejected. Episodes are
  persisted because *detecting* them means an expensive scan of raw wire data.
  A season is roughly 26 lanes × 56 days of arithmetic over declared config, so
  a table would be cost with no benefit, and a rebuild/invalidate story for
  something this cheap is pure overhead.
- **Attach a measurement to the *nearest* cohort completion** — rejected: it is
  ambiguous at midpoints and silently attaches measurements that fall in
  crop-free weeks. The rule is instead "the cohort whose completion window
  contains the date" (`end <= observed < end + interval`), which on an interval
  grid matches at most one cohort and inverts cleanly to "started a duration
  earlier".
- **Let each measurement define its own cohort** — rejected: it cannot render
  the parallel overlap, which is the point of the view.

## Consequences

- A measurement attaching to *no* cohort is returned to the caller and shown on
  the page, not dropped. Red's cycle dates are provisional, and this is the
  feedback loop that corrects them — it fired on the first real render,
  flagging 2025-08-07 as outside every cohort.
- `exposure` always returns a coverage fraction beside its value, and returns
  `None` rather than `0` or `NaN` for an empty window, so "no data" and
  "genuinely zero" never blur. The page reports coverage in prose; the chart
  shows it as gaps in the projected bar.
- A climate metric is a `(device, sensor)` pair in `metadata.yaml`, so moving one
  onto a per-height wire device later is a config edit, not a redesign — the
  payoff of modelling heights as devices (red ADR 0001).
- Blue's adapter is unbuilt. The types are shaped for it, and are simpler for
  having dropped the phase seam that only blue would have used.
