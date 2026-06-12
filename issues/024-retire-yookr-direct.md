# Epic: retire yookr-direct and drop the `project` column (deferred)

**Status:** Deferred — blocked on datalake-green (see exit criteria)

## Design source

Full plan, blockers, dedup-race ordering constraint, exit criteria, and sequence
in `docs/blue/yookr-direct-retirement.md`; prod coverage snapshot in
`docs/blue/yookr-vs-datalake-coverage.md`.

## Summary

Make the SPoHF datalake the single canonical automated source and remove: the
`yookr-direct` ingest, the dual-source toggle (`datasource.py`, `yookr.py`, the
`is_yookr` branch in `ops.py`), and the `readings.project` column (blue → a single
categorical, like red's `source`).

Deferred because prod shows the datalake relay (`yookr-data`) currently failing
(316 failures) and stale across every automated sensor, with 5 devices missing —
so retiring `yookr-direct` today is a broad coverage regression, not a cleanup.

## Exit criteria — do NOT start until ALL hold

- [ ] `sync_metadata.yookr-data` shows `last_run_success = true` with recent,
      non-zero records over several consecutive runs
- [ ] The coverage query (see retirement doc) shows **every** automated
      `(device, sensor)` fresh under `project <> 'yookr-direct'`, with no missing
      devices

## Sequence (once unblocked)

Per `docs/blue/yookr-direct-retirement.md`:

1. Stop the `yookr-direct` sync (cronjob)
2. Purge `project = 'yookr-direct'` rows — required because the dedup index excludes
   `project` and the upsert never rewrites it, so a resync alone can't reclaim
   yookr-owned keys
3. Resync / let the datalake re-own the keys; re-verify coverage
4. Collapse the dashboard to a single datalake source; remove the toggle plumbing
5. Drop the `project` column
6. Delete `sync/yookr_orchestrator.py`, the `yookr/` client, and related config

## Blocked by

- Datalake relay health (upstream SPoHF) — external
- Issue 023 (GDD decoupled to OpenMeteo) must land first, so removing `yookr-direct`
  does not break GDD
