# Admin risk-episode audit view

**Status:** ready-for-agent

## Design source

Red ADR `src/wp6_data/red/docs/adr/0002-prescriptive-risk-rebuildable-episode-cache.md`
and the **Risk episode** term in `src/wp6_data/red/CONTEXT.md`.

## What to build

An admin-gated (`verify_session_admin`) view listing the persisted **risk episodes**
from the issue-015 cache for a selectable date range — the quality-control log of when a
risk at a height was present/observed and when it was resolved/gone. On-page HTML table
(CSV export is a later follow-up). Each row states the **threshold-set** that produced
the episode, so episodes from different threshold eras are never silently conflated.

## Acceptance criteria

- [ ] Admin-gated view lists risk episodes for a selected date range, read from the cache
- [ ] Columns: growth section, risk type, present-from, resolved-at, duration, peak value, threshold-set
- [ ] Open (unresolved) episodes shown distinctly from closed ones
- [ ] Threshold-set provenance visible per row
- [ ] Reads the cache only — no recomputation
- [ ] Sensible empty state when no episodes exist for the range

## Deferred / out of scope

CSV/export download; immutable audit semantics (the cache is rebuildable, so the log reflects current thresholds after a Rebuild).

## Blocked by

- `issues/015-rebuildable-episode-cache.md`
