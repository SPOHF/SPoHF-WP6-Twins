"""View model for the blue "Seasons" page.

Same split as red's crop-cycles view model, and as ``monitor``'s: a pure
computation that turns config plus two frames into drawable lanes, and a thin
wrapper adding the provider reads.

Blue's lane axis is the **treatment**, not a cohort. Every treatment is measured
over the same season, so the lanes stack rather than stagger — there is no
overlap to draw, because a blueberry bush carries one crop per season. What the
picture is for is the *vertical* comparison: nine plots that lived through one
weather, and how their fruit differed.

A treatment is sampled many times across a season — several plants, and several
harvest passes — so the rows summarise into one outcome per lane, the way the
measure declares. Two levels, because one is not enough for a yield: ``agg``
combines the plants picked on *one* pass, and ``period_agg`` combines those
passes into the season. A yield is ``avg`` then ``sum``; averaging throughout
gives a per-plant-per-pass figure about a third of the season's, and summing
throughout totals every plant and pass into a plot figure still labelled "per
plant". A measure that declares no ``period_agg`` keeps the flat behaviour: one
aggregation over every reading in the season.

Measurements that fall in no declared season are carried out, not dropped: they
are the signal that the season dates are wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.cycles import Cohort, exposure
from wp6_data.shared.series import SeriesMetric, daily_series, observations
from wp6_data.shared.twin import SensorDataProvider
from wp6_data.shared.waterfall import Lane, Marker

from .config import SeasonConfig, SeasonsConfig


@dataclass(frozen=True)
class Unattached:
    """A measurement that fell outside every declared season."""

    day: date
    device: str
    value: float


@dataclass(frozen=True)
class SeasonsView:
    """Everything the blue seasons page renders, across every declared season."""

    lanes: list[Lane] = field(default_factory=list)
    daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    unattached: list[Unattached] = field(default_factory=list)

    @property
    def partial(self) -> list[Lane]:
        """Lanes whose season is incompletely covered by weather data."""
        return [lane for lane in self.lanes if lane.coverage < 1.0]

    @property
    def measured(self) -> list[Lane]:
        return [lane for lane in self.lanes if lane.markers]


def _season_for(day: date, seasons: list[SeasonConfig]) -> SeasonConfig | None:
    """The season containing ``day``, or None. Seasons do not overlap."""
    for season in seasons:
        if season.start <= day < season.end:
            return season
    return None


def _summarise(by_day, within, across, agg: str, period_agg: str) -> Marker:
    """One outcome for a lane, and a plain phrase saying how it was reached."""
    samples = sum(len(v) for v in by_day.values())
    if across is None:
        value = float(within(pd.Series([v for vs in by_day.values() for v in vs])))
        detail = f"{CHART_AGG_FUNCS[agg]} of {samples}" if samples > 1 else ""
    else:
        per_occasion = [
            float(within(pd.Series(by_day[day]))) for day in sorted(by_day)
        ]
        value = float(across(pd.Series(per_occasion)))
        detail = (
            f"{CHART_AGG_FUNCS[period_agg]} of {len(per_occasion)} picks "
            f"({CHART_AGG_FUNCS[agg]} of {samples} samples)"
        )
    return Marker(value=round(value, 2), samples=samples, detail=detail)


def build_seasons(
    seasons: list[SeasonConfig],
    treatments: dict[str, str],
    observed: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    weather_agg: str = "avg",
    measure_agg: str = "avg",
    measure_period_agg: str = "",
) -> SeasonsView:
    """Lanes for every (season, treatment), with outcomes and coverage.

    ``treatments`` maps device name to display label, in the order lanes should
    be drawn. A lane is emitted for every declared treatment even when it was
    never sampled — an absent plot is a fact about the season worth seeing, and
    the bar shows it by carrying no chip.
    """
    if measure_agg not in CHART_AGG_FUNCS:
        raise ValueError(
            f"unknown measure agg {measure_agg!r}; "
            f"expected one of {sorted(CHART_AGG_FUNCS)}"
        )
    if measure_period_agg and measure_period_agg not in CHART_AGG_FUNCS:
        raise ValueError(
            f"unknown measure period agg {measure_period_agg!r}; "
            f'expected one of {sorted(CHART_AGG_FUNCS)} or "" for flat'
        )
    within = getattr(pd.Series, CHART_AGG_FUNCS[measure_agg])
    across = (
        getattr(pd.Series, CHART_AGG_FUNCS[measure_period_agg])
        if measure_period_agg else None
    )

    # Keyed by the day as well as the lane: a day's readings are one occasion —
    # the plants picked on one pass — and `Plant_nr` is discarded on ingest
    # (ADR 0004), so samples sharing a date *are* the per-plant dimension.
    grouped: dict[tuple[str, str], dict[date, list[float]]] = {}
    unattached: list[Unattached] = []
    for row in observed.itertuples(index=False):
        season = _season_for(row.date, seasons)
        if season is None or row.device not in treatments:
            unattached.append(Unattached(row.date, row.device, float(row.value)))
            continue
        by_day = grouped.setdefault((season.label, row.device), {})
        by_day.setdefault(row.date, []).append(float(row.value))

    lanes: list[Lane] = []
    for season in sorted(seasons, key=lambda s: s.start):
        _, coverage = exposure(season.start, season.end, daily, weather_agg)
        for device, label in treatments.items():
            by_day = grouped.get((season.label, device), {})
            markers = (
                # No label: the lane is already named for the treatment, so
                # the hover reads "Std · Brix: 10.1" rather than "Std · Std".
                [_summarise(by_day, within, across, measure_agg, measure_period_agg)]
                if by_day else []
            )
            lanes.append(
                Lane(
                    cohort=Cohort(
                        cycle_label=season.label,
                        key=f"{season.label}:{device}",
                        label=label,
                        start=season.start,
                        end=season.end,
                    ),
                    group=season.label,
                    markers=markers,
                    coverage=coverage,
                )
            )
    return SeasonsView(lanes=lanes, daily=daily, unattached=unattached)


async def assemble_seasons(
    provider: SensorDataProvider,
    config: SeasonsConfig,
    metric: SeriesMetric,
    sensor: str,
    treatments: dict[str, str],
    timezone: str,
    measure_agg: str = "avg",
    measure_period_agg: str = "",
) -> SeasonsView:
    """:func:`build_seasons` plus the weather and measurement reads.

    Both reads span every declared season in one call rather than one per
    season: the gap between seasons is a few months, so a single window costs
    less than the extra round trips.
    """
    if not config.seasons:
        return SeasonsView()

    first = min(s.start for s in config.seasons)
    last = max(s.end for s in config.seasons)

    daily = await daily_series(provider, metric, first, last, timezone)
    observed = await observations(
        provider, list(treatments), sensor, first, last, timezone,
    )
    return build_seasons(
        config.seasons, treatments, observed, daily,
        weather_agg=metric.agg, measure_agg=measure_agg,
        measure_period_agg=measure_period_agg,
    )
