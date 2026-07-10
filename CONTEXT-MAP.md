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
