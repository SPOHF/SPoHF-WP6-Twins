# Context Map

This platform hosts three digital twins. Each keeps its own domain language;
`shared/` is twin-agnostic and must not mention twin specifics.

## Contexts

- [Red](./src/wp6_data/red/CONTEXT.md) — tomato greenhouse twin: light (PAR), DLI, and plant-growth microclimate
- [Blue](./src/wp6_data/blue/CONTEXT.md) — blueberry farm twin: soil, leaf and microclimate sensors, GDD, treatments
- Grey — synthetic test twin exercising generic platform functionality

## Relationships

- The twins do not know about each other; they share only the generic platform in `shared/`.

## Shared shape

Both Red and Blue store readings in TimescaleDB with a single categorical
`readings.source` separating manual uploads from automated ingest. Blue reached
this shape in July 2026 by retiring its second automated pipeline and dropping
the `project` column ([`docs/blue/yookr-direct-retirement.md`](./docs/blue/yookr-direct-retirement.md));
`project` no longer exists anywhere and should not be reintroduced.

Both twins also share a model of **overlapping periods** (`shared/cycles.py`,
`shared/waterfall.py`, [ADR 0006](./docs/adr/0006-cycles-and-cohorts-shared-model.md)):

- **Cycle** — a named, dated span of activity, declared in a twin's config.
  Cycles may be separated by inactive gaps.
- **Cohort** — an undivided unit that begins every *interval* within a cycle and
  lasts a *duration*. When duration exceeds interval, cohorts overlap and
  several are in flight at once.
- **Exposure** / **Coverage** — a daily series aggregated over a span, always
  paired with the share of that span which actually had data. An aggregate over
  a partial window is never presented as if complete.

What a lane *means* stays twin-side. A cohort carries no developmental stages:
that was modelled and removed, because red's stage boundaries were fixed offsets
from the start date — see [ADR 0006](./docs/adr/0006-cycles-and-cohorts-shared-model.md).
