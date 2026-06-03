# Canopy-deficit verdict indicator in the table

**Status:** ready-for-agent

## Design source

Red ADR `src/wp6_data/red/docs/adr/0002-prescriptive-risk-rebuildable-episode-cache.md`
and the **Canopy light deficit** / **Risk episode** terms in `src/wp6_data/red/CONTEXT.md`.

## What to build

Surface the **persisted per-section verdict** (from the issue-015 cache) in the
crop-climate table — primarily the **Canopy light deficit** indicator at H1, plus any
active-risk markers per section — reading the *"as of last build"* state. This is the
**discrete judgment**, distinct from the threshold-free trendlines of issue 016: render
it as a small status marker, with the freshness ("as of <time>") visible. No
recomputation on page load — reads the cache only.

## Acceptance criteria

- [ ] H1 row shows the canopy-deficit verdict (under / at / over target) read from the cache
- [ ] Per-section active-risk markers reflect the last-built state
- [ ] Freshness timestamp shown; clearly distinguished from the threshold-free trendlines
- [ ] Reads the cache only — no engine recomputation on page load
- [ ] Renders sensibly when the cache is empty (never built yet)

## Deferred / out of scope

Auto-refresh of the verdict (still "as of last build" until issue-015's buttons or a future cron run).

## Blocked by

- `issues/013-crop-climate-readonly-table.md`
- `issues/015-rebuildable-episode-cache.md`
