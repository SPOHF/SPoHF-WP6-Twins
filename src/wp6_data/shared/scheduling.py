"""Run a job once a day, inside the process that owns its output.

Both twins train models on boot and write them to disk. Once that disk is a
PVC the models survive a deploy, which is the point — but it also means they
stop improving, because a refit only ever happened on a cold boot. This module
puts the refit back on a clock.

**Why in-process rather than a Kubernetes CronJob.** A CronJob was the obvious
shape — the chart already runs the nightly exports that way — and it is the
wrong one here, for two reasons the export CronJob itself documents:

- *The volume.* The models PVC is ReadWriteOnce on the only StorageClass the
  cluster has, and the dashboard holds its attachment for its whole lifetime.
  A second pod mounting it must be pinned to the dashboard's node or it sits
  Pending on a Multi-Attach error — the failure that silently broke both twins'
  exports for 23 days after the v2 migration (see ``_export-affinity.tpl``).
  A job running *inside* the dashboard cannot hit it at all.
- *Cache coherence.* A model written by another pod is only picked up by code
  that re-reads it from disk. Red's climate chain does; red's DLI model holds
  it in a module global. So a CronJob would refit DLI into a file the running
  dashboard would ignore until its next restart, which is precisely the thing
  we are trying to stop depending on.

The training code already runs in this process for the boot bootstrap and the
admin retrain button, under a lock that a scheduled run shares. This adds a
clock, not a new place for training to happen.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta

import structlog

log = structlog.get_logger(__name__)

# A scheduled run that fails should not wedge the schedule, but it should not
# spin either: back off to this before the next attempt rather than retrying at
# full speed against a database that is evidently unhappy.
RETRY_DELAY_SECONDS = 15 * 60


def parse_daily_time(value: str) -> time | None:
    """``"03:00"`` as a :class:`~datetime.time`, or ``None`` when unset.

    Unset means *no schedule*, which is the right default for local development:
    scheduling is a deployment concern, and a dev machine running the dashboard
    overnight should not quietly start retraining models at 3 a.m.
    """
    value = value.strip()
    if not value:
        return None
    try:
        hour, _, minute = value.partition(":")
        return time(int(hour), int(minute or 0), tzinfo=UTC)
    except ValueError:
        log.warning("daily_schedule_unparsable", value=value)
        return None


def seconds_until(moment: time, *, now: datetime) -> float:
    """Seconds from ``now`` to the next occurrence of ``moment``.

    Always strictly in the future: asking at exactly the scheduled time yields
    tomorrow's run, not a zero-length sleep that would fire twice.
    """
    target = datetime.combine(now.date(), moment)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily(
    job: Callable[[], Awaitable[None]], *, at: time, name: str,
) -> None:
    """Await ``job`` once a day at ``at``, forever.

    Never raises except :class:`asyncio.CancelledError`, which is allowed
    through so shutdown can stop the task. A job that raises is logged and
    retried after :data:`RETRY_DELAY_SECONDS`; the daily rhythm resumes at the
    next scheduled time either way.
    """
    while True:
        delay = seconds_until(at, now=datetime.now(UTC))
        log.info("daily_job_scheduled", job=name, in_seconds=round(delay))
        await asyncio.sleep(delay)
        try:
            await job()
            log.info("daily_job_finished", job=name)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("daily_job_failed", job=name, exc_info=True)
            await asyncio.sleep(RETRY_DELAY_SECONDS)
