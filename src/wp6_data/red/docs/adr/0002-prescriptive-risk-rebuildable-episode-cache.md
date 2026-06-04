# Prescriptive risk as a rebuildable, admin-triggered episode cache

## Status

accepted

## Context

The "Crop Climate by Height" view (`/multi_height/crop-climate`) adds the red
twin's first *prescriptive* surface: per-growth-section risk indicators
(Fungal-risk wet-hours, out-of-band VPD, canopy light deficit) derived from the
multi-height wire. Two needs were stated: a **live per-section verdict** on the
page ("is this section at risk now?"), and a **quality-control log of risk
episodes** — when a risk at a height was first present/observed and when it was
resolved/gone (see `CONTEXT.md`: *Risk episode*).

Every other red view is read-only over the `(device, sensor)` contract; red has
no in-process scheduler (periodic work is a k8s `CronJob` running a console-script
entrypoint, e.g. `wp6-data-sync`), and derived data is already materialised into
tables read cheaply (`sensors_daily_summary` cagg, `daily_coverage`).

Three facts shaped the decision:

- **A live verdict needs a long, growing lookback.** The wet-hours accumulator
  depends on history before the displayed day, and that history grows without
  bound. Recomputing it on *every page load* is the genuine cost.
- **Thresholds are provisional** (RH cutoff + window, VPD band, DLI target,
  episode min-duration) — possibly hallucinated from the proto sketch, and will
  be retuned.
- **The external `wire_sensors` table is retained forever** and is currently
  small, so any historic window can be recomputed cheaply at any time.

This decision was **revisited twice** during design (the trail matters):
1. First settled as *compute-on-read, no persistence* — rejected once the live
   verdict requirement (long lookback per page load) made on-read recomputation
   too costly to do per request.
2. Then considered as a *background cron + persisted table* — the scheduling was
   dropped from v1 in favour of a manual button, to avoid infra work (a red-specific
   CronJob, helm + argocd changes) while the feature is young.

## Decision

Persist risk episodes in a **rebuildable cache table** in red's TSDB, maintained
by **admin-triggered actions**, and read cheaply by the page. No scheduler in v1.

- The episode detector is a **pure function** `(readings, thresholds) →
  (current_state, episodes)`, exercised first via a CLI before any persistence.
- Two admin-gated (`verify_session_admin`) actions write the cache:
  **Update** (incremental — extend the log to now; the manual stand-in for a
  cron) and **Rebuild** (recompute a *selectable date range* from retained raw
  data; used after a threshold retune).
- Each episode row **stamps the threshold-set** it was computed under, so a
  rebuild is explicit and two threshold eras are never silently conflated.
- The page reads the last-written state: the live verdict is **"as of the last
  Update/Rebuild"**, and the live trendlines remain threshold-free, computed on
  read for the displayed day (cheap, like `wire-trends`).

The trendline (continuous, always shown) and the episode (discrete,
threshold-bound, persisted) are two renderings of one metric, so retuning a
threshold + Rebuild changes the log without touching the dashboard code.

## Considered Options

- **Compute-on-read, no persistence**: rejected — a live per-section verdict over
  a growing lookback can't be recomputed per page load. (Was the initial choice.)
- **Background cron + persisted table from v1**: deferred, not rejected — correct
  end-state, but the scheduler needs a red-specific CronJob + helm/argocd work not
  worth it yet. The button is the manual equivalent; promoting to a cron later is
  "call the same entrypoint on a schedule", not a rewrite.
- **Immutable, append-only audit**: rejected for v1 — enshrining episodes computed
  from admittedly-provisional thresholds has no QC value; rebuildability is what
  lets thresholds be iterated. Becomes a natural follow-up once thresholds stabilise
  (rebuilds stop, and the log is effectively immutable on its own).
- **Per-cell absolute-threshold coloring in the live table**: rejected — implies
  trust in guessed thresholds; the table colors **relatively across heights** instead.

## Consequences

- v1 gains red's first **view-authored write path** and a new cache table, but no
  scheduler and no infra changes — the trigger is a button a human presses.
- The live verdict can be **stale** (until someone presses Update). Accepted for
  v1; the deferred cron is exactly the upgrade that makes it auto-fresh.
- The log is **reproducible, not immutable**: a range Rebuild rewrites that range
  under current thresholds. Threshold-set stamping keeps this auditable.
- Hammering the buttons triggers redundant recomputation; acceptable (guard by
  disabling while a build runs — no locking infra).
- **Promotion path is additive**: same pure engine, wrapped in (a) a CronJob for
  auto-refresh and (b) an immutable audit table once thresholds stabilise — each
  the trigger to supersede this ADR.
