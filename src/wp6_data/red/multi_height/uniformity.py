"""Cross-wire view-model for the red "Uniformity across wires" page.

Every declared **Multi-height wire** carries the same five **Growth sections**
(see red ``CONTEXT.md`` — the H→section mapping is fixed and identical on every
wire), so H3 on one wire is directly comparable to H3 on another. That makes a
disagreement between wires *meaningful*: either the greenhouse genuinely differs
where they hang, or a wire is not reading what its neighbours read.

The module is pure — no I/O — so it is unit-testable without a database, the
same seam :func:`~wp6_data.red.multi_height.view_model.build_crop_climate_day`
draws. It computes no climate maths of its own: it calls that per-wire builder
once per wire and only pivots, compares and classifies what comes back.

Two things it refuses to do quietly:

- **Average over absence.** A wire that reported for part of the day is excluded
  from the spread and carries its coverage, rather than being folded in and
  reading as agreement.
- **Report a spread without saying what kind.** A uniform offset at every height
  (placement or calibration) and a single height out of line (a real local
  microclimate) are different findings and must not look alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd  # type: ignore[import-untyped]

from ..db import wire_device_id
from ..growth_sections import GrowthSection
from ..risk.config import RiskThresholds
from .config import METRIC_SOURCES, UniformityConfig
from .data import filter_for_day
from .view_model import build_crop_climate_day

### How each metric collapses to one comparable number per day ###
# This follows from what the metric *is*, not from anyone's judgement, so it
# lives beside the metric vocabulary rather than in config:
#   - par/temp/hum/co2/vpd are instantaneous, so the day's mean is the level;
#   - Height DLI is already a cumulative integral, so its last point is the day;
#   - fungal wet-hours is a running accumulation, so its peak is the claim.
# Comparing day aggregates rather than latest readings matters here in
# particular: ``received_at`` is the relay's burst-insert time (CONTEXT
# "Reading time"), so two wires' latest readings are minutes apart.
MEAN, LAST, MAX = "mean", "last", "max"
METRIC_AGG = {
    "par": MEAN, "temp": MEAN, "hum": MEAN, "co2": MEAN, "vpd": MEAN,
    "dli": LAST,
    "fungal": MAX,
}

### Verdict kinds ###
VERDICT_OFFSET = "offset"        # the same drift at every height
VERDICT_DIVERGENT = "divergent"  # one height out of line with the rest
VERDICT_AGREES = "agrees"        # within the notable spread everywhere
VERDICT_EXCLUDED = "excluded"    # too little coverage to compare at all


def aggregate(values: list[float], metric: str) -> float | None:
    """Collapse one section's day series to the number the wires are compared on."""
    if not values:
        return None
    agg = METRIC_AGG[metric]
    if agg == LAST:
        return float(values[-1])
    if agg == MAX:
        return float(max(values))
    return float(sum(values) / len(values))


### View model ###


@dataclass(frozen=True)
class WireCell:
    """One wire's reading of one growth section, for the selected metric."""

    wire: str
    aggregate: float | None
    latest: float | None
    series: list[float]
    coverage_hours: int
    # False when the wire reported too little of the day to be compared. The
    # cell still renders — with its coverage — it just does not move the spread.
    comparable: bool


@dataclass(frozen=True)
class SectionRow:
    """One growth section across every declared wire."""

    height: int
    label: str
    cells: list[WireCell]
    spread: float | None  # max - min over comparable cells; None below two
    median: float | None


@dataclass(frozen=True)
class WireVerdict:
    """How one wire sits against the others, over the whole profile.

    Carries the finding, not the sentence: the unit belongs to presentation, so
    the page renders the prose from these fields (the pattern ``crop_cycles``
    established, where the route turns view-model properties into notes).
    """

    wire: str
    kind: str  # one of the VERDICT_* constants
    offset: float | None       # typical delta vs the per-height wire median
    worst_height: int | None   # the height carrying the largest residual
    worst_delta: float | None
    # The wire's best-covered section — "did this wire report today at all".
    # Its weakest section would let one dead height speak for the whole wire;
    # the per-section detail is in the cells, where it belongs.
    coverage_hours: int
    # How many sections actually went into the finding. A verdict drawn from one
    # section is a much weaker claim than one drawn from five, and must say so.
    sections_compared: int


@dataclass(frozen=True)
class UniformityDay:
    """Everything the uniformity page renders for one metric on one day."""

    day_start: pd.Timestamp
    metric: str
    wires: list[str]
    rows: list[SectionRow]
    verdicts: list[WireVerdict]
    # The metric's configured notable spread — the tint's saturation point and
    # the verdict threshold, carried so the legend can never drift from either.
    notable_spread: float

    @property
    def comparable_wires(self) -> list[str]:
        return [v.wire for v in self.verdicts if v.kind != VERDICT_EXCLUDED]

    @property
    def worst_spread(self) -> float | None:
        spreads = [r.spread for r in self.rows if r.spread is not None]
        return max(spreads) if spreads else None


def _coverage_hours(
    df_day: pd.DataFrame, device: str, metric: str, timezone: str,
) -> int:
    """Distinct local hours in which ``device`` observed ``metric`` that day.

    Hours rather than row counts: the relay writes in bursts (CONTEXT "Reading
    time"), so a row count says how chatty the relay was, not how much of the
    day was actually observed.

    Counted against the metric's *source* measurements, not the device: the
    wires do not all report the same four measurements, so a device busy with
    PAR must not be credited with having observed temperature. Where a metric
    has two parents (VPD), only the hours both reported count — the derivation
    needs them together.
    """
    if df_day.empty:
        return 0
    rows = df_day[df_day["device"] == device]
    if rows.empty:
        return 0
    hours = None
    for measurement in METRIC_SOURCES[metric]:
        times = rows.loc[rows["measurement"] == measurement, "time"]
        seen = set(times.dt.tz_convert(timezone).dt.floor("h").unique())
        hours = seen if hours is None else (hours & seen)
    return len(hours or ())


# A verdict is judged on a wire's distance from the *median*, while the
# configured threshold is a **spread** — the gap between the outermost wires.
# The two are not the same size: two wires sitting half a notable spread either
# side of the median are exactly one notable spread apart. Halving the threshold
# is what keeps the Spread column and the verdicts telling one story; without
# it, two wires had to disagree by twice the configured amount before any
# sentence said so.
DELTA_SHARE_OF_SPREAD = 0.5


def _verdict(
    wire: str,
    deltas: dict[int, float],
    coverage_hours: int,
    notable: float,
) -> WireVerdict:
    """Classify one wire's per-height deltas against the wire median.

    ``offset`` is the drift the wire carries everywhere; ``residual`` is what is
    left once that drift is taken out. A wire that is uniformly off has a large
    offset and small residual — it reads the same shape, shifted. A wire whose
    residual is itself notable is not shifted but *different*, at one height.
    """
    apart = notable * DELTA_SHARE_OF_SPREAD
    ordered = sorted(deltas.items())
    offset = float(pd.Series([d for _, d in ordered]).median())
    worst_height, worst_delta = max(ordered, key=lambda kv: abs(kv[1] - offset))
    residual = abs(worst_delta - offset)

    if residual >= apart:
        kind = VERDICT_DIVERGENT
    elif abs(offset) >= apart:
        kind = VERDICT_OFFSET
    else:
        kind = VERDICT_AGREES
    return WireVerdict(
        wire, kind, offset, worst_height, float(worst_delta), coverage_hours,
        len(deltas),
    )


def build_uniformity_day(
    df: pd.DataFrame,
    wires: list[str],
    sections: list[GrowthSection],
    thresholds: RiskThresholds,
    config: UniformityConfig,
    metric: str,
    timezone: str,
    target_date: date | None = None,
) -> UniformityDay:
    """Every declared wire's growth sections, side by side, for one metric.

    ``df`` is the tidy readings frame for the day plus the fungal look-back —
    the same window the crop-climate page fetches, and unscoped by wire, which
    is what makes this view a re-read of one query rather than N.
    """
    df_day, day_start = filter_for_day(df, timezone, target_date=target_date)
    notable = config.notable_spread[metric]

    # One call per wire into the existing pure builder: every metric for every
    # section, computed exactly as the single-wire page computes it.
    by_wire = {
        wire: build_crop_climate_day(
            df, wire, sections, thresholds, timezone, target_date=target_date,
        )
        for wire in wires
    }
    coverage = {
        (wire, section.height): _coverage_hours(
            df_day, wire_device_id(wire, section.height), metric, timezone,
        )
        for wire in wires
        for section in sections
    }

    rows: list[SectionRow] = []
    deltas: dict[str, dict[int, float]] = {wire: {} for wire in wires}
    for index, section in enumerate(sections):
        cells = []
        for wire in wires:
            series = by_wire[wire].sections[index].metric_series(metric)
            hours = coverage[(wire, section.height)]
            cells.append(WireCell(
                wire=wire,
                aggregate=aggregate(series, metric),
                latest=float(series[-1]) if series else None,
                series=series,
                coverage_hours=hours,
                comparable=(
                    bool(series) and hours >= config.min_coverage_hours
                ),
            ))

        values = [c.aggregate for c in cells if c.comparable and c.aggregate is not None]
        # A spread needs two readings to be a spread; one wire is not a
        # comparison and must not render as perfect agreement.
        spread = (max(values) - min(values)) if len(values) >= 2 else None
        median = float(pd.Series(values).median()) if values else None
        rows.append(SectionRow(
            height=section.height, label=section.label,
            cells=cells, spread=spread, median=median,
        ))

        # Deltas only mean something once there is something to differ from:
        # a lone reporting wire would otherwise "agree" with itself.
        if spread is not None:
            for cell in cells:
                if cell.comparable and cell.aggregate is not None:
                    deltas[cell.wire][section.height] = cell.aggregate - median

    verdicts = []
    for wire in wires:
        hours = max((coverage[(wire, s.height)] for s in sections), default=0)
        if not deltas[wire]:
            verdicts.append(
                WireVerdict(wire, VERDICT_EXCLUDED, None, None, None, hours, 0)
            )
        else:
            verdicts.append(_verdict(wire, deltas[wire], hours, notable))

    return UniformityDay(
        day_start=day_start,
        metric=metric,
        wires=list(wires),
        rows=rows,
        verdicts=verdicts,
        notable_spread=notable,
    )
