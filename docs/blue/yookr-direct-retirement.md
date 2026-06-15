# Retiring yookr-direct — blockers & exit criteria

**Status: deferred — BLOCKED ON UPSTREAM (SPoHF) as of 2026-06-15.** Goal: make the
SPoHF datalake the single canonical automated source and remove the `yookr-direct`
ingest + the dual-source toggle + the `project` column. See the coverage snapshot:
[`yookr-vs-datalake-coverage.md`](./yookr-vs-datalake-coverage.md).

## ⛔ Hard blocker (confirmed 2026-06-15): the relay serves one sensor per device

A direct comparison of the `yookr-data` relay API against yookr-direct (both pull
the same yookr sensors) shows the **relay exposes only ONE sensor per device**:

| source | series (3-day window) | rows | weatherstation:airTemperature |
|---|---|---|---|
| yookr-direct | **58** (full sensor set per device) | 8,738 | present, fresh |
| `yookr-data` relay | **21** (one sensor per device) | 2,362 | **absent** |

Non-artifactual: a single 6-hour page returns 47 rows / 10 devices with **zero**
devices reporting >1 sensor (soil → only `soilMoisture`, row sensors → only
`temperature`, `weatherstation` → only `windspeedGust`). This is an **upstream bug
in `backoffice.spohf.com/api/v1/data/yookr-data`** — not fixable on our side, and
not fixable by any amount of re-syncing or re-tagging.

⇒ **yookr-direct cannot be retired until SPoHF fixes the relay to expose every
sensor per device.** This supersedes the issues below (all real, but secondary).

## Why it's deferred (the secondary problems)

1. **~~The datalake relay sync is failing.~~** *(RESOLVED 2026-06-15: the API token
   had been revoked → `401 Unauthorized`; restored, sync recovered — 6,803 records,
   fresh. But it only ingests the one-sensor-per-device subset above.)*
2. **The datalake is stale across every automated sensor.** Was a symptom of the
   401 outage (and, for absorbed series, of the dedup race below) — not a fixed
   property. With the token restored the relay is fresh, but still incomplete.
3. **Five automated devices appeared entirely absent from the datalake** (`366D`,
   `366E`, `3670`, `3672` row sensors; `PH1 | 4D1D` soil-pH). Mostly the 401
   outage; the relay now returns them — but only their single exposed sensor.
4. **The dedup race makes a naive resync ineffective.** `readings`' unique key is
   `(device_name, sensor_tag, time)` — no `project` — and the upsert's
   `ON CONFLICT … DO UPDATE` rewrites `value`/`raw_value` but **never `project`**.
   So any key first inserted by `yookr-direct` stays `project='yookr-direct'`
   forever; a datalake resync overwrites its *value* but can't reclaim ownership.
   ⇒ retirement must be ordered: **stop yookr-direct → purge `project='yookr-direct'`
   rows (frees the keys) → resync/let the datalake re-own them.**
5. **`project` can only be dropped once there's a single ingest.** While both syncs
   write the shared table, `project` is the only thing distinguishing them, and the
   dedup race persists. So "drop the `project` column" is a *consequence* of
   retiring `yookr-direct`, not an independent step. (Blue would then mirror red's
   single-categorical model.)

## Already handled (so they're NOT blockers)

- **GDD's dependency on `yookr-direct` weather** — removed by decoupling GDD to
  OpenMeteo modeled weather at the farm location (separate work). GDD no longer
  reads `readings` for temperature, so it survives yookr-direct removal.
- **`/status` masking the staleness** — the coverage grid showed the datalake as
  healthy because `daily_coverage` has no `project` column, so it leaked
  yookr-direct's fresh days into the datalake view. Fixed separately (cagg join at
  day granularity).

## Exit criteria — retire only when ALL hold

- [ ] **(BLOCKING, upstream) The `yookr-data` relay exposes every sensor per
      device.** Verify with the relay-API diff: enumerate distinct
      `(device, sensor)` from `GET /api/v1/data/yookr-data` over a recent window
      and confirm it matches yookr-direct's full set (58 series, incl.
      `weatherstation:airTemperature`) — not one sensor per device. Owned by SPoHF.
- [ ] `sync_metadata.yookr-data` shows `last_run_success = true` with recent,
      non-zero records over several consecutive runs.
- [ ] Re-running the coverage query (below) shows **every** automated
      `(device, sensor)` fresh (last day ≈ today) under the datalake filter
      (`project <> 'yookr-direct'`), with **no missing devices**.

> Note: the third check can only pass *after* yookr-direct stops owning the dedup
> keys (it absorbs the datalake's identical-timestamp rows — see problem 4). So in
> practice: confirm the relay is complete via the **API diff** (check 1), then the
> retirement sequence below frees the keys and the in-DB check becomes meaningful.

```sql
SELECT device_name, sensor_tag,
  max(time) FILTER (WHERE project <> 'yookr-direct')::date AS dl_last
FROM readings GROUP BY device_name, sensor_tag
ORDER BY dl_last NULLS FIRST;   -- NULL/old rows at top = still-missing/stale
```

## Retirement sequence (once exit criteria met)

1. Stop the `yookr-direct` sync (cronjob).
2. Purge `project = 'yookr-direct'` rows (frees the dedup keys).
3. Resync / let the datalake re-own the keys; re-verify coverage.
4. Collapse the dashboard to a single datalake source; remove the toggle,
   `datasource.py`, `yookr.py`, and the `is_yookr` branch in `ops.py`.
5. Drop the `project` column (blue → single-categorical, like red).
6. Delete `sync/yookr_orchestrator.py`, `yookr/` client, and related config.
