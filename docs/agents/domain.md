# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root — it points at one `CONTEXT.md` per
  twin. Read each one relevant to the topic.
- **`docs/adr/`** — platform-wide ADRs. Read the ones that touch the area
  you're about to work in.
- **`src/wp6_data/<twin>/docs/adr/`** — twin-scoped decisions, when present.

If any of these files don't exist, **proceed silently**. Don't flag their
absence or suggest creating them upfront. The producer skill
(`/grill-with-docs`) creates them lazily when terms or decisions get resolved.

## File structure

Multi-context repo (root `CONTEXT-MAP.md` present):

```
/
├── CONTEXT-MAP.md                      ← points to each twin's CONTEXT.md
├── docs/adr/                           ← platform-wide decisions (0001-…)
└── src/wp6_data/
    ├── shared/                          ← twin-agnostic platform code
    ├── red/
    │   ├── CONTEXT.md
    │   └── docs/adr/                    ← red-specific decisions
    ├── blue/
    │   ├── CONTEXT.md
    │   └── docs/adr/
    └── grey/
        └── CONTEXT.md
```

The twin boundary is also an architectural one (see `CLAUDE.md`): `shared/`
must not mention red/blue/grey specifics, and the twins must not know about
each other. Keep each twin's domain language in its own `CONTEXT.md`.

## Use the glossary's vocabulary

When your output names a domain concept (an issue title, a refactor proposal, a
hypothesis, a test name), use the term as defined in the relevant twin's
`CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either
you're inventing language the project doesn't use (reconsider) or there's a
real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than
silently overriding:

> _Contradicts ADR-0002 (long-data per-year scoped replace) — but worth
> reopening because…_
