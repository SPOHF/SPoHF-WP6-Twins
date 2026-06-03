"""Risk-episode detection — contiguous spans a metric stays "active".

Structural and risk-agnostic: callers pass a tidy frame with ``time``, ``value``
(a severity where higher = worse) and ``active`` (bool, "is the risk on for this
reading"). The engine decides what "active" means per risk (above a threshold,
below a target, outside a band) and tags the resulting spans with section /
risk / threshold-set. A configured minimum duration suppresses flapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd


@dataclass
class Episode:
    """One contiguous risk span. ``end is None`` means still active (open)."""

    start: datetime
    end: datetime | None
    peak: float


def _finalize(
    start: datetime,
    end: datetime | None,
    peak: float,
    last_active: datetime,
    min_duration: timedelta,
) -> Episode | None:
    """Build an episode if it lasted at least ``min_duration``, else drop it.

    Duration runs from ``start`` to the resolution time (``end``) for a closed
    span, or to the last active reading for an open one.
    """
    measured_end = end if end is not None else last_active
    if (measured_end - start) < min_duration:
        return None
    return Episode(start=start, end=end, peak=float(peak))


def detect_episodes(df: pd.DataFrame, min_duration: timedelta) -> list[Episode]:
    """Find active spans in ``df`` (columns ``time``, ``value``, ``active``).

    ``end`` is the first inactive timestamp after the span (when it resolved), or
    ``None`` if the span is still active at the end of the data. ``peak`` is the
    maximum ``value`` over the span. Spans shorter than ``min_duration`` are
    dropped as flapping.
    """
    if df.empty:
        return []

    d = df.sort_values("time")
    episodes: list[Episode] = []
    start: datetime | None = None
    peak = 0.0
    last_active: datetime | None = None

    for row in d.itertuples(index=False):
        if row.active:
            if start is None:
                start, peak = row.time, float(row.value)
            else:
                peak = max(peak, float(row.value))
            last_active = row.time
        elif start is not None:
            ep = _finalize(start, row.time, peak, last_active, min_duration)
            if ep is not None:
                episodes.append(ep)
            start = None

    if start is not None:
        ep = _finalize(start, None, peak, last_active, min_duration)
        if ep is not None:
            episodes.append(ep)

    return episodes
