"""Cycles and cohorts — a twin-agnostic model of overlapping periods.

Both twins want the same shape of answer: *what conditions did this thing
experience while it was developing?* The vocabulary that question needs is
generic, so it lives here rather than in either twin.

- A **cycle** is a named, dated span of activity, declared in a twin's config.
  Cycles may be separated by inactive gaps (a crop-free winter, a dormancy).
- A **cohort** is a unit that begins every ``interval`` within a cycle and lasts
  ``duration``. When ``duration > interval`` cohorts *overlap*, and several are
  in flight on any given day — which is the whole reason this module exists
  rather than a plain date-range helper.
- **Exposure** aggregates a daily series over a span, always paired with a
  **coverage** fraction, so a partial window is never mistaken for a complete one.

A cohort is deliberately *undivided*. Subdividing it into named developmental
stages was tried and removed: the stage boundaries were fixed offsets from the
start, so they carried no information the start date did not already carry, and
they cost a colour axis that the observed conditions now use instead.

Spans are half-open ``[start, end)`` throughout, so contiguity is checkable by
equality rather than by off-by-one arithmetic.

Twin-agnostic by contract (CLAUDE.md): nothing here may name a twin, a crop or a
measurement. Anything that needs those words belongs in the twin package — see
``generate_cohorts`` on how a twin adds its own dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared.aggregation import CHART_AGG_FUNCS

# `exposure` speaks the platform's aggregation vocabulary (avg/min/max/sum),
# not pandas': the same config value is handed to the provider for bucketing,
# so one name has to serve both. CHART_AGG_FUNCS already maps the platform
# key onto the pandas op, and is the single source of truth for both.


@dataclass(frozen=True)
class CohortSpec:
    """How cohorts recur within a cycle, and how long each one lasts."""

    interval: timedelta
    duration: timedelta

    def __post_init__(self) -> None:
        if self.interval <= timedelta(0):
            raise ValueError(f"interval must be positive, got {self.interval}")
        if self.duration <= timedelta(0):
            raise ValueError(f"duration must be positive, got {self.duration}")

    @property
    def overlap(self) -> int:
        """How many cohorts are in flight at once in steady state."""
        return -(-self.duration // self.interval)  # ceil


@dataclass(frozen=True)
class CycleSpec:
    """One declared span of activity. ``end`` is exclusive."""

    label: str
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"cycle {self.label!r} ends before it starts")


@dataclass(frozen=True)
class Cohort:
    """One cohort, resolved to concrete dates. ``end`` is exclusive."""

    cycle_label: str
    key: str
    label: str
    start: date
    end: date


def generate_cohorts(cycle: CycleSpec, spec: CohortSpec) -> list[Cohort]:
    """Every cohort that fits wholly inside ``cycle``, oldest first.

    Cohorts start on an ``interval`` grid from ``cycle.start`` and are emitted
    only while a *whole* cohort still fits before ``cycle.end`` — a cohort that
    would be cut off by the cycle ending is not a cohort that ripened, and
    showing a truncated one would misreport its exposure.

    Any *additional* dimension (a treatment, a variety, a plot) is the caller's
    fan-out: call this once per group and tag the resulting lanes. Keeping that
    out of here is what lets one twin do "cohort per week" and another do
    "cohort per treatment per year" without this function growing an axis.
    """
    cohorts, start = [], cycle.start
    while start + spec.duration <= cycle.end:
        cohorts.append(
            Cohort(
                cycle_label=cycle.label,
                key=start.isoformat(),
                label=f"wk {start.isocalendar().week:02d} · {start:%d %b}",
                start=start,
                end=start + spec.duration,
            )
        )
        start += spec.interval
    return cohorts


def cohort_for_date(
    observed_on: date, cohorts: list[Cohort], interval: timedelta
) -> Cohort | None:
    """The cohort an observation on ``observed_on`` belongs to, or None.

    An observation attaches to the cohort whose **completion window** contains
    it — ``cohort.end <= observed_on < cohort.end + interval``. On an interval
    grid that is at most one cohort, and it inverts cleanly to
    "started ``duration`` before the observation".

    Returns None rather than guessing when the date falls outside every window
    (an inactive gap, or before the first cohort completed). Callers should
    surface that: an observation that attaches to nothing is the signal that the
    declared cycle dates are wrong, not a row to drop.
    """
    for cohort in cohorts:
        if cohort.end <= observed_on < cohort.end + interval:
            return cohort
    return None


def overlap_at(day: date, cohorts: list[Cohort]) -> list[Cohort]:
    """The cohorts in flight on ``day`` (``start <= day < end``), oldest first."""
    return [c for c in cohorts if c.start <= day < c.end]


def exposure(
    start: date,
    end: date,
    daily: pd.DataFrame,
    agg: str = "avg",
    *,
    date_col: str = "date",
    value_col: str = "value",
) -> tuple[float | None, float]:
    """Aggregate ``daily`` over the half-open span, with a coverage fraction.

    ``agg`` is a platform aggregation key (``avg``/``min``/``max``/``sum``), the
    same vocabulary the provider buckets with.

    Returns ``(value, coverage)`` where coverage is the share of the span's days
    carrying a non-null value. ``value`` is None when the span has no data at
    all — never NaN and never 0, so "no data" and "genuinely zero" stay distinct.

    Coverage travels with the value on purpose: an aggregate over a half-covered
    window is a different claim from one over a full window, and the caller is
    expected to show the difference rather than quietly present both alike.
    """
    if agg not in CHART_AGG_FUNCS:
        raise ValueError(
            f"unknown agg {agg!r}; expected one of {sorted(CHART_AGG_FUNCS)}"
        )

    span_days = (end - start).days
    if span_days <= 0:
        return None, 0.0
    if daily.empty or date_col not in daily or value_col not in daily:
        return None, 0.0

    days = pd.to_datetime(daily[date_col]).dt.date
    window = daily[(days >= start) & (days < end)]
    values = pd.to_numeric(window[value_col], errors="coerce").dropna()
    if values.empty:
        return None, 0.0

    coverage = min(1.0, len(values) / span_days)
    return float(getattr(values, CHART_AGG_FUNCS[agg])()), coverage
