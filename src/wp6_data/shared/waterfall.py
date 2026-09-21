"""The waterfall: overlapping cohorts as staggered lanes over a calendar.

One lane per :class:`~wp6_data.shared.cycles.Cohort`, drawn as a bar from its
start to its end. Because cohorts overlap, the lanes stagger diagonally — and a
*vertical slice* at any date shows exactly which cohorts were in flight.

The daily series is **projected onto the lanes**: a lane's bar is coloured, day
by day, by the conditions that cohort was actually living through. That turns
the chart's one colour axis into the thing the page exists to answer — a spell
of weather reads as a band of colour cutting across precisely the cohorts it
touched — and it makes data coverage self-evident, because a day with no reading
leaves the pale bar showing through rather than being silently averaged over.

Each lane's outcome values are written on small chips just past the *end* of its
bar — where the outcome was observed, when the cohort completed — and outside it,
so the number never hides the climate that produced it. A chip's fill says where
its value sits against every other value on show, so the highest and lowest
readings of a season are findable without reading a single number; its outline
says which series it belongs to.

Two consequences of projecting rather than drawing a separate strip:

- there is no fading for partial coverage. Dimming a bar that encodes a value by
  colour would corrupt the reading; the gaps already say it, and more precisely.
- days outside every cohort are not drawn at all. The series is shown where it
  acted on something, not as a record for its own sake.

Twin-agnostic by contract (CLAUDE.md): a lane is a dated span with an optional
outcome value. What a lane *means* is the twin's business; see
``shared.cycles.generate_cohorts``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]

from wp6_data.shared.cycles import Cohort

ROW_HEIGHT = 26          # px per lane row; also drives the figure height
LANE_HEIGHT = 0.7        # share of a row the bar fills, leaving lanes distinct
GROUP_GAP_ROWS = 1       # blank rows inserted between groups
BAND_COLOR = "rgba(99,102,241,0.06)"
RULE_COLOR = "#d1d5db"
# The bar under the projection: what shows through on days that reported
# nothing, so an unobserved cohort is still visibly a cohort.
LANE_COLOR = "#e5e7eb"
COLOR_SCALE = "RdYlBu_r"
# One colour per outcome series, assigned in sorted order so a series keeps its
# colour across renders. These ring the value chip — its *fill* is the value.
VALUE_COLORS = ("#0f172a", "#b45309", "#065f46", "#6d28d9")
VALUE_FONT_SIZE = 10
# The chip fill: where a value sits between the smallest and largest on show.
# Purple appears nowhere in COLOR_SCALE, so the two readings never blur into
# one another — a chip is never mistaken for the bar behind it.
VALUE_SCALE = ("#f3e8ff", "#d8b4fe", "#a855f7", "#7e22ce", "#581c87")
# Chips sit *past* the harvest end rather than on the bar: their width is fixed
# in pixels while a bar's is fixed in days, so on a multi-season axis a stack of
# chips would blot out the last weeks of the very climate the lane exists to
# show. Successive chips step rightwards in pixels, so their spacing does not
# change with the zoom level or the season's length.
CHIP_BORDER_WIDTH = 1.5
CHIP_BORDER_PAD = 2
# Clear space between two chips sharing one harvest end.
CHIP_GAP = 7
# Plotly exposes no text metrics, so a chip's width is estimated from its text.
# The estimate is deliberately the *widest* of Plotly's default font stack
# (Open Sans, Verdana, Arial) rather than an average: which face a browser
# actually resolves is not ours to know, and a pitch a pixel too wide is
# invisible where one a pixel too narrow overprints. Verdana has the widest
# digits of the three at 0.636 em; separators are roughly half that.
DIGIT_EM = 0.64
SEPARATOR_EM = 0.34
# Room for the colorbar. Chips overhang into it, so it grows with the stack.
MARGIN_RIGHT = 90


@dataclass(frozen=True)
class Marker:
    """An outcome observed for a lane. ``series`` pairs markers on one lane.

    One marker per series per lane: a lane may be sampled several times over
    its span, but the chip says how the lane *turned out*, so the caller
    summarises those samples into one value before it gets here. ``samples``
    carries how many went in, and appears on hover — a mean of eight readings
    and a single reading are different claims and should not look alike.
    """

    value: float
    label: str = ""
    series: str = ""
    samples: int = 1
    # How the value was arrived at, in the caller's own words ("mean of 8",
    # "sum of 3 picks, 135 samples"). Shown on hover, because a summarised
    # figure and a single reading are different claims and must not look alike.
    # A phrase rather than a rule: what counts as an occasion is the twin's
    # vocabulary, and this module has none.
    detail: str = ""


@dataclass(frozen=True)
class Lane:
    """One cohort as drawn: its bar, its outcome markers, and its data coverage.

    ``group`` drives banding and spacing — lanes sharing a group hug together
    and get one label in the left margin. A twin uses it for whatever its second
    dimension is (a cycle, a treatment, a plot).

    ``coverage`` is the share of the cohort's span that actually had data. The
    chart no longer dims by it — the gaps in the projected bar show it directly —
    but callers still report it in prose, so it stays on the lane.
    """

    cohort: Cohort
    group: str = ""
    markers: list[Marker] = field(default_factory=list)
    coverage: float = 1.0


def _rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(start: str, end: str, t: float) -> str:
    """``start`` to ``end``, ``t`` of the way."""
    a, b = _rgb(start), _rgb(end)
    r, g, b_ = (round(x + (y - x) * t) for x, y in zip(a, b, strict=True))
    return f"#{r:02x}{g:02x}{b_:02x}"


def _ink(background: str) -> str:
    """Readable text colour for a chip filled with ``background``."""
    r, g, b = _rgb(background)
    # Perceived brightness (ITU-R BT.601): green dominates, blue barely counts.
    return "#111827" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#ffffff"


def value_range(lanes: list[Lane]) -> tuple[float, float] | None:
    """Smallest and largest outcome on show, or None when nothing was measured.

    The range spans *every* series rather than each one separately: the values
    are the same measurement of the same thing, so scaling them apart would make
    two different cultivars' readings look alike when they are not.
    """
    values = [m.value for lane in lanes for m in lane.markers]
    return (min(values), max(values)) if values else None


def value_color(value: float, span: tuple[float, float]) -> str:
    """``value``'s colour on :data:`VALUE_SCALE`, relative to ``span``."""
    low, high = span
    # A single distinct value has no relative position; the midpoint is the only
    # honest answer, and it avoids implying "highest" from a lone reading.
    t = 0.5 if high <= low else (value - low) / (high - low)
    step = t * (len(VALUE_SCALE) - 1)
    i = min(int(step), len(VALUE_SCALE) - 2)
    return _mix(VALUE_SCALE[i], VALUE_SCALE[i + 1], step - i)


def _chip_text(marker: Marker) -> str:
    """What a chip reads — the single place the value is formatted.

    Both the drawing and the width estimate go through here, so a change to the
    format can never leave the spacing measuring a different string.
    """
    return f"{marker.value:g}"


def chip_pitch(lanes: list[Lane]) -> int:
    """Pixels between two chips sharing one harvest end.

    Derived from the widest value actually on show, not fixed: a chip is sized
    by its own text, so a constant step tuned to ``8.4`` leaves ``135.7`` and
    its neighbour overprinting. Taking the widest rather than each chip's own
    width keeps the stack on a regular grid, which reads as a column of values
    instead of a ragged run.
    """
    widest = max(
        (
            sum(
                DIGIT_EM if ch.isdigit() else SEPARATOR_EM
                for ch in _chip_text(marker)
            )
            for lane in lanes
            for marker in lane.markers
        ),
        default=0.0,
    )
    box = widest * VALUE_FONT_SIZE + 2 * (CHIP_BORDER_PAD + CHIP_BORDER_WIDTH)
    return round(box + CHIP_GAP)


def series_colors(lanes: list[Lane]) -> dict[str, str]:
    """Series name to colour, assigned in sorted order.

    Exposed so a caller can caption the values with the same colours the chart
    used, rather than re-deriving the order and drifting out of step.
    """
    names = sorted({m.series for lane in lanes for m in lane.markers})
    return {
        name: VALUE_COLORS[i % len(VALUE_COLORS)] for i, name in enumerate(names)
    }


def _positions(lanes: list[Lane]) -> list[int]:
    """Row index per lane: consecutive within a group, a blank row between.

    Rows are whole numbers and uniformly spaced because the projection is a
    heatmap, whose cell height comes from the gap between neighbouring rows —
    an uneven gap would draw one lane fatter than the rest. A group break is
    therefore a *skipped row* rather than a fractional offset.
    """
    pos: list[int] = []
    row, prev = 0, None
    for lane in lanes:
        if prev is None:
            row = 0
        elif lane.group != prev:
            row += 1 + GROUP_GAP_ROWS
        else:
            row += 1
        pos.append(row)
        prev = lane.group
    return pos


def _group_decorations(lanes, pos):
    """Alternating band, separator rule and margin label per group of lanes."""
    shapes, annotations = [], []
    i, band = 0, 0
    while i < len(lanes):
        group = lanes[i].group
        j = i
        while j < len(lanes) and lanes[j].group == group:
            j += 1
        if band % 2 == 1:
            shapes.append(
                dict(
                    type="rect", xref="paper", x0=0, x1=1, yref="y",
                    y0=pos[i] - 0.5, y1=pos[j - 1] + 0.5,
                    layer="below", line_width=0, fillcolor=BAND_COLOR,
                )
            )
        if i > 0:
            edge = (pos[i - 1] + pos[i]) / 2
            shapes.append(
                dict(
                    type="line", xref="paper", x0=0, x1=1, yref="y",
                    y0=edge, y1=edge, line=dict(color=RULE_COLOR, width=1),
                )
            )
        if group:
            annotations.append(
                dict(
                    xref="paper", x=0, xanchor="right", xshift=-96,
                    yref="y", y=(pos[i] + pos[j - 1]) / 2,
                    text=f"<b>{group}</b>", showarrow=False,
                    font=dict(size=11, color="#374151"),
                )
            )
        i, band = j, band + 1
    return shapes, annotations


def _daily_values(
    daily: pd.DataFrame | None, date_col: str, value_col: str
) -> dict[date, float]:
    """The daily series as a plain date→value lookup, nulls dropped."""
    if daily is None or daily.empty:
        return {}
    if date_col not in daily or value_col not in daily:
        return {}
    days = pd.to_datetime(daily[date_col]).dt.date
    values = pd.to_numeric(daily[value_col], errors="coerce")
    return {
        day: float(value)
        for day, value in zip(days, values, strict=True)
        if pd.notna(value)
    }


def _projection(lanes, pos, rows, by_day):
    """The (days, z) heatmap grid: the daily series clipped to each lane's span.

    Cells outside a cohort's window — and days it reported nothing for — stay
    None, which Plotly leaves transparent so the lane bar shows through.
    """
    first = min(lane.cohort.start for lane in lanes)
    last = max(lane.cohort.end for lane in lanes)
    days = [first + timedelta(days=i) for i in range((last - first).days)]
    column = {day: i for i, day in enumerate(days)}

    z: list[list[float | None]] = [[None] * len(days) for _ in range(rows)]
    for lane, row in zip(lanes, pos, strict=True):
        day = lane.cohort.start
        while day < lane.cohort.end:
            value = by_day.get(day)
            if value is not None:
                z[row][column[day]] = value
            day += timedelta(days=1)
    return days, z


def _value_chips(lanes, pos, colors, span, marker_label, pitch):
    """One annotation per outcome value, just past the end of its lane's bar.

    The end is where the value came from: an outcome is observed when the cohort
    *completes* (see ``cycles.cohort_for_date``, which attaches an observation to
    the cohort whose completion window contains it), so a chip drawn part-way
    along the bar would claim it was measured mid-development.

    They sit *outside* the bar rather than on it. A chip is a fixed number of
    pixels wide and a bar is a fixed number of days, so once several cycles share
    one axis the stack covers the bar's final weeks — hiding the ripening climate
    behind the very number it produced, and putting the mark back in the
    mid-development position the paragraph above rules out.

    Several series share one harvest end, so they step rightwards from it in
    pixels — a date offset would open and close as the axis rescaled — reading
    left to right in the same order a caller legends them. The chip's fill is
    where its value sits in ``span``; its outline is which series it belongs to.
    """
    order = list(colors)
    chips = []
    for lane, row in zip(lanes, pos, strict=True):
        for marker in lane.markers:
            idx = order.index(marker.series)
            fill = value_color(marker.value, span)
            chips.append(
                dict(
                    x=lane.cohort.end, y=row, xref="x", yref="y",
                    xanchor="left",
                    # First series sits just clear of the harvest date; later
                    # ones step forward one pitch each. The gap keeps the chip's
                    # edge off the bar's instead of fusing with it.
                    xshift=idx * pitch + CHIP_GAP,
                    text=_chip_text(marker), showarrow=False,
                    font=dict(size=VALUE_FONT_SIZE, color=_ink(fill)),
                    bgcolor=fill,
                    bordercolor=colors[marker.series],
                    borderwidth=CHIP_BORDER_WIDTH,
                    borderpad=CHIP_BORDER_PAD,
                    hovertext=(
                        f"{lane.cohort.label} · "
                        f"{marker.label or marker.series or marker_label}: "
                        f"{marker.value:g}"
                        + (f" ({marker.detail})" if marker.detail else "")
                    ),
                )
            )
    return chips


def render_waterfall(
    lanes: list[Lane],
    daily: pd.DataFrame | None = None,
    *,
    series_label: str = "",
    marker_label: str = "",
    date_col: str = "date",
    value_col: str = "value",
) -> str | None:
    """Inline Plotly HTML for the waterfall, or None when there is nothing to draw.

    ``lanes`` are drawn in the order given (oldest first reads best). ``daily``
    is a ``date``/``value`` frame projected onto the lane bars; without it the
    bars render plain. Returning None rather than an empty figure lets the caller
    show a plain note, matching the convention used elsewhere in the codebase.
    """
    if not lanes:
        return None

    pos = _positions(lanes)
    rows = pos[-1] + 1
    colors = series_colors(lanes)

    fig = go.Figure()

    # The bar itself is a shape rather than a trace: Plotly draws heatmaps
    # beneath scatter traces whatever order they are added in, so a scatter
    # "background" would sit on top of the projection it is meant to back.
    bars = [
        dict(
            type="rect", xref="x", yref="y",
            x0=lane.cohort.start, x1=lane.cohort.end,
            y0=row - LANE_HEIGHT / 2, y1=row + LANE_HEIGHT / 2,
            layer="below", line_width=0, fillcolor=LANE_COLOR,
        )
        for lane, row in zip(lanes, pos, strict=True)
    ]

    by_day = _daily_values(daily, date_col, value_col)
    if by_day:
        days, z = _projection(lanes, pos, rows, by_day)
        fig.add_trace(
            go.Heatmap(
                x=days, y=list(range(rows)), z=z,
                colorscale=COLOR_SCALE,
                # A cell is one row tall minus the gap, matching the bar beneath.
                ygap=round(ROW_HEIGHT * (1 - LANE_HEIGHT)),
                hoverongaps=False,
                showscale=True,
                colorbar=dict(
                    title=dict(text=series_label, side="right", font=dict(size=10)),
                    len=0.22, y=1, yanchor="top", thickness=12,
                    tickfont=dict(size=9),
                ),
                hovertemplate=(
                    f"%{{x|%d %b %Y}}<br>{series_label or 'value'}: %{{z:.1f}}"
                    "<extra></extra>"
                ),
            )
        )

    shapes, annotations = _group_decorations(lanes, pos)
    span = value_range(lanes)
    # The chips overhang the last lane's bar, so the right margin has to hold
    # the whole stack. The colorbar shares that margin without contention: lanes
    # run oldest-first from the top, so a bar reaching the right edge is always
    # near the bottom, while the colorbar sits in the top fifth.
    gutter = 0
    if span is not None:
        pitch = chip_pitch(lanes)
        annotations += _value_chips(
            lanes, pos, colors, span, marker_label, pitch
        )
        gutter = len(colors) * pitch + CHIP_GAP

    first = min(lane.cohort.start for lane in lanes)
    last = max(lane.cohort.end for lane in lanes)
    pad = timedelta(days=max(1, round((last - first).days * 0.02)))

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=ROW_HEIGHT * rows + 140,
        margin=dict(l=190, r=MARGIN_RIGHT + gutter, t=30, b=40),
        shapes=bars + shapes, annotations=annotations,
        hovermode="closest",
        showlegend=False,
    )
    fig.update_xaxes(range=[first - pad, last + pad], tickformat="%d %b")
    fig.update_yaxes(
        tickmode="array", tickvals=pos,
        ticktext=[lane.cohort.label for lane in lanes],
        tickfont=dict(size=10),
        range=[rows - 0.5, -0.5],  # reversed: earliest on top
        showgrid=False, zeroline=False,
    )

    return fig.to_html(
        full_html=False, include_plotlyjs="cdn",
        config={"responsive": True, "displaylogo": False},
    )
