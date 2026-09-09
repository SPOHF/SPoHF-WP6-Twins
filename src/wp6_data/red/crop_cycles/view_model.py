"""View model for the red "Crop cycles" waterfall.

Splits the page into a pure computation and a thin set of reads, the same way
``multi_height/view_model.py`` does:

- :func:`build_waterfall` turns cohorts, measurements and a daily climate frame
  into drawable lanes. No I/O, so the attachment and coverage logic — the parts
  most worth getting right — are unit-testable without a database.
- :func:`assemble_waterfall` adds the two provider reads.

Measurements that attach to no cohort are **carried out, not dropped**. They are
the signal that the configured cycle dates are wrong, and the page says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.cycles import (
    Cohort,
    CohortSpec,
    cohort_for_date,
    exposure,
    generate_cohorts,
)
from wp6_data.shared.series import daily_series, observations
from wp6_data.shared.twin import SensorDataProvider
from wp6_data.shared.waterfall import Lane, Marker

from .config import ClimateMetric, CropCyclesConfig, CycleConfig, to_cohort_spec, to_cycle_spec


@dataclass(frozen=True)
class Unattached:
    """A measurement that fell outside every cohort's completion window."""

    day: date
    device: str
    value: float


@dataclass(frozen=True)
class WaterfallView:
    """Everything the crop-cycles page renders, across every declared cycle."""

    lanes: list[Lane] = field(default_factory=list)
    daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    unattached: list[Unattached] = field(default_factory=list)

    @property
    def partial(self) -> list[Lane]:
        """Lanes whose development window is incompletely covered by climate.

        The chart shows this directly, as gaps in the projected bar; this is
        what lets the page also say it in words.
        """
        return [lane for lane in self.lanes if lane.coverage < 1.0]

    @property
    def measured(self) -> list[Lane]:
        return [lane for lane in self.lanes if lane.markers]


def build_waterfall(
    cohorts: list[Cohort],
    spec: CohortSpec,
    observations: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    device_labels: dict[str, str],
    agg: str = "avg",
    measure_agg: str = "avg",
) -> WaterfallView:
    """Lanes for ``cohorts``, with measurements attached and coverage computed.

    ``observations`` carries ``date, device, value``; each row attaches to the
    cohort whose completion window contains its date. Both cultivars share a
    lane — a cohort is keyed by the week fruit set, not by cultivar — so they
    arrive as two markers distinguished by ``series``. That assumes both follow
    the same development model, which is v1's stated simplification.

    A cohort can be sampled more than once for the same cultivar — several
    berries off one truss, or two passes in the completion week — so the rows
    are **summarised into one marker per (cohort, cultivar)**. How they combine
    is ``measure_agg``, which comes from the measure's own metadata: "avg" for
    anything measured per item (a concentration, a per-berry weight), "sum" for
    a total over the window such as a yield picked across several harvests.
    Averaging a total would report a fraction of the real figure.
    """
    grouped: dict[tuple[str, str], list[float]] = {}
    unattached: list[Unattached] = []

    for row in observations.itertuples(index=False):
        cohort = cohort_for_date(row.date, cohorts, spec.interval)
        if cohort is None:
            unattached.append(Unattached(row.date, row.device, float(row.value)))
            continue
        label = device_labels.get(row.device, row.device)
        grouped.setdefault((cohort.key, label), []).append(float(row.value))

    if measure_agg not in CHART_AGG_FUNCS:
        raise ValueError(
            f"unknown measure agg {measure_agg!r}; "
            f"expected one of {sorted(CHART_AGG_FUNCS)}"
        )
    summarise = getattr(pd.Series, CHART_AGG_FUNCS[measure_agg])

    by_key: dict[str, list[Marker]] = {}
    for (key, label), values in grouped.items():
        by_key.setdefault(key, []).append(
            Marker(
                value=round(float(summarise(pd.Series(values))), 2),
                label=label, series=label, samples=len(values),
            )
        )

    # One series present means no pairing, so drop the series tag and let the
    # chart centre the value in its bar rather than spreading it along one.
    only_one = len({m.series for markers in by_key.values() for m in markers}) <= 1
    if only_one:
        by_key = {
            key: [Marker(m.value, m.label, samples=m.samples) for m in markers]
            for key, markers in by_key.items()
        }

    lanes = []
    for cohort in cohorts:
        _, coverage = exposure(cohort.start, cohort.end, daily, agg)
        lanes.append(
            Lane(
                cohort=cohort,
                group=cohort.cycle_label,
                markers=by_key.get(cohort.key, []),
                coverage=coverage,
            )
        )
    return WaterfallView(lanes=lanes, daily=daily, unattached=unattached)


async def assemble_waterfall(
    provider: SensorDataProvider,
    config: CropCyclesConfig,
    cycles: list[CycleConfig],
    metric: ClimateMetric,
    sensor: str,
    devices: dict[str, str],
    timezone: str,
    measure_agg: str = "avg",
) -> WaterfallView:
    """:func:`build_waterfall` plus the climate and measurement reads.

    Every declared cycle is generated and drawn together — the cycles are the
    waterfall's ``group`` axis, and reading one season against the next is the
    point of the page, so there is nothing to choose between. Cycles are
    separated by inactive gaps, which show up honestly as a stretch of climate
    with no lanes under it.

    Reads span the whole declared period in one call each rather than one per
    cycle: the gap between cycles is a handful of weeks, so a single window
    costs less than the extra round trips. The measurement window reaches one
    interval past the last cycle end so a cohort completing on the final day can
    still pick up its harvest sample.
    """
    spec = to_cohort_spec(config)
    cohorts = [
        cohort
        for cycle in sorted(cycles, key=lambda c: c.start)
        for cohort in generate_cohorts(to_cycle_spec(cycle), spec)
    ]
    if not cohorts:
        return WaterfallView()

    first = min(c.start for c in cycles)
    last = max(c.end for c in cycles)

    daily = await daily_series(provider, metric, first, last, timezone)
    observed = await observations(
        provider, list(devices), sensor, first, last + spec.interval, timezone,
    )
    return build_waterfall(
        cohorts, spec, observed, daily,
        device_labels=devices, agg=metric.agg,
        measure_agg=measure_agg,
    )
