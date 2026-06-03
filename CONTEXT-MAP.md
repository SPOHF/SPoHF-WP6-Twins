# Context Map

This platform hosts three digital twins. Each keeps its own domain language;
`shared/` is twin-agnostic and must not mention twin specifics.

## Contexts

- [Red](./src/wp6_data/red/CONTEXT.md) — tomato greenhouse twin: light (PAR), DLI, and plant-growth microclimate
- Blue — blueberry farm twin (glossary not yet started)
- Grey — synthetic test twin exercising generic platform functionality

## Relationships

- The twins do not know about each other; they share only the generic platform in `shared/`.
