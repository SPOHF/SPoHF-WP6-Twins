# Trained models persist across a deploy, and carry a fingerprint of what fitted them

## Status

accepted — supersedes the arrangement described in `blue/routes/monitor/soil_forecast.py`
and `red/dashboard.py` before this change

## Context

Both twins trained models into the container's own writable layer: red's DLI
model and climate chain under `~/.wp6/models`, blue's soil forecasters under
`~/.wp6/blue-models`. That layer dies with the pod, so every deploy, OOM kill,
node drain and reschedule threw the models away and the dashboard refitted them
on boot.

This was a deliberate choice, and it bought something real. An artifact could
not outlive the code that wrote it, so a refactor could never serve numbers
from a model fitted by different code — the accident enforced correctness. It
also meant every restart refitted against more data, which for the climate
chain is not incidental: retraining is when it re-decides whether link 3 has
seen enough winter to earn a day-of-year term, and which greenhouse-level
reference wins on end-to-end skill.

What it cost was a gap after every deploy. Red's climate chain takes ~55 s to
fit, and it is backgrounded so the pod reports Ready before the model exists —
so the model-backed pages show "not trained yet" to whoever looks first. That
is on top of the dashboard being down for the pod swap anyway, because the
deployment is `Recreate` (it mounts ReadWriteOnce volumes).

## Decision

**Persist the models on a small per-twin PVC, refit them nightly in-process,
and gate every load on a fingerprint of the code contract and the configuration
that produced the artifact.**

The three parts are one decision; any two without the third is worse than what
was there before.

### Persist

A `<release>-<twin>-models` PVC, mounted at `/data/models`. Separate from
`manual-uploads` because a model is a derived artifact that can be thrown away
and rebuilt, and it should not turn up in backups of real uploaded data.

ReadWriteOnce is safe for the same reason the existing volumes are: both
dashboards are single-replica with `strategy: Recreate`, so no two pods hold
the volume at once.

### Refit on a clock, inside the dashboard

Persisting alone would freeze the models at whenever they were first fitted,
which for the climate chain forfeits the self-tuning described above. So a
nightly refit restores that rhythm: red at 03:00 UTC, blue at 03:30.

**Not a Kubernetes CronJob**, though the chart already runs the nightly exports
that way, for two reasons:

- *The volume.* A second pod mounting a RWO PVC the dashboard holds must be
  pinned to the dashboard's node or it sits Pending on a Multi-Attach error.
  That is not hypothetical — it silently broke both twins' nightly exports for
  23 days after the v2 cluster migration, and is why `_export-affinity.tpl`
  exists. A job running inside the dashboard cannot hit it.
- *Cache coherence.* A model written by another pod is only picked up by code
  that re-reads it from disk. Red's climate chain does; red's DLI model holds it
  in a module global. A CronJob would refit DLI into a file the running
  dashboard ignores until its next restart — reintroducing the dependency on
  restarts that this change is removing.

Training already runs in-process for the boot bootstrap and the admin button,
under a lock the scheduled run shares. This adds a clock, not a new place for
training to happen.

### Fingerprint every artifact

A hand-maintained version constant is not sufficient, because it only catches
the changes somebody remembered to declare. Two kinds that bite:

- **A configuration change.** Widen `training_start`, add a horizon, add an
  exclusion window — none of that changes the pickle's layout, so a version gate
  waves it through and the model keeps answering the question it was fitted to.
  Under ephemeral storage this was invisible because the next boot refitted
  anyway; persistence makes it a live hazard.
- **A quiet code change.** Add a feature to a fit, rename a field. The pickle
  loads; the numbers are wrong.

So `shared/artifacts.fingerprint` hashes the things that must match, and each
twin stores the result beside the model:

- Red's climate chain stores `ClimateModelConfig.fit_fingerprint()` — the whole
  config, because every field shapes the fit. Checked in `read_artifact`.
- Blue's soil models get an `artifact.json` stamp covering a version, the sensor
  list and `SoilForecaster.__init__`'s signature. Blue previously had **no gate
  at all** — a bare `pickle.load` — so this is the largest change in kind.

A mismatch means "no usable artifact", which every caller already handles: it is
the same answer they got when the file was absent, and it routes into the refit
that already exists. The version constants stay alongside, for the deliberate
break no fingerprint can see — a change in what the stored numbers *mean* while
their shape is unchanged.

## Consequences

- A deploy no longer costs a refit. The model-backed pages are populated as soon
  as the pod is Ready.
- A `metadata.yaml` edit now forces a refit on the next boot, which it did not
  before — it was previously picked up only by the accident of restarting.
- Red's DLI model keeps its existing versioned *migration* path (`version >= 5`,
  `>= 6` branches at version 7), which forwards old artifacts rather than
  refusing them. Under persistence a migrated artifact can now live indefinitely.
  Left as-is because those branches are deliberate and tested, but it is the
  weakest of the three rails and the place to look first if a stale DLI model is
  ever suspected.
- Blue's stamp does not see an attribute added inside `fit` rather than
  `__init__`. The per-file load in `_load_models` is the net for that, and is why
  a load failure is now logged loudly instead of printed and passed over.
- Nightly refits are silent by design (they must not wedge the schedule). A
  persistent failure shows up as a model that stops advancing, not as an error
  on a page. `daily_job_failed` in the logs is the signal.

## Alternatives considered

- **Keep ephemeral storage.** Zero risk of a stale artifact, at the cost of the
  post-deploy gap and of never improving except by restart. Rejected once the
  gap became a routine annoyance rather than a theoretical one.
- **Persist without a schedule.** Simplest, and the one originally proposed.
  Rejected because it freezes a model whose whole design assumes retraining —
  red's wires have only ~65 days of history, so each month is a large relative
  gain.
- **Persist without fingerprints, relying on the version constants.** Rejected:
  it depends on memory for exactly the changes that are easiest to forget, and
  blue had no constant to bump in the first place.
- **Store the release SHA and refit when it changes.** Catches every code change
  and no config change, and refits on every deploy — which is what we were
  trying to stop.
