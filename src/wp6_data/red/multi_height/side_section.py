"""Side-section view-model and renderer for the red multi-height wires.

Shows the *latest* reading of every installed **Multi-height wire** as a
cross-section of the greenhouse: one column per wire, heights H1 (top) to H5
(bottom), and a field interpolated linearly between the wires and between the
heights. Pure (no I/O) like :mod:`.uniformity`, so it is testable without a
database; the route only fetches readings and hands them in.

Wire positions are not known (only "a few metres apart"), so the wires are
spread evenly across the greenhouse rectangle in sorted wire-id order. The
section is therefore only correct if wire ids follow the physical row order.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from ..db import WIRE_SENSOR_HEIGHTS
from ..utils import PAR_COLORSCALE, value_to_color
from .svg import SectionLayout


@dataclass(frozen=True)
class MeasurementStyle:
    """Colour scale, narrowest range it may be stretched over, decimals shown.

    The minimum span keeps a near-constant reading from being painted as a
    gradient (e.g. 0.3 °C of noise). ``zero_is_dead`` marks measurements where
    exactly 0 is physically impossible, so it means a dead sensor: the value is
    shown but left out of the interpolation. PAR is 0 at night, so it is not.
    """

    colorscale: object
    min_span: float
    decimals: int
    zero_is_dead: bool


MEASUREMENT_STYLES = {
    "par": MeasurementStyle(PAR_COLORSCALE, 50.0, 0, zero_is_dead=False),
    "temp": MeasurementStyle("RdYlBu_r", 2.0, 1, zero_is_dead=True),
    "hum": MeasurementStyle("YlGnBu", 5.0, 1, zero_is_dead=True),
    "co2": MeasurementStyle("Purples", 50.0, 0, zero_is_dead=True),
}
DEFAULT_STYLE = MEASUREMENT_STYLES["temp"]
CELL_PX = 12
REPLAY_CELL_PX = 36  # coarse: every frame carries its own grid, so the page stays small
SCALE_PAD_SHARE = 0.05
BOX_H_PX = 18


@dataclass(frozen=True)
class NodeReading:
    """``stale``: too old for its replay frame; shown greyed, never interpolated."""

    value: float
    time: pd.Timestamp
    stale: bool = False


@dataclass(frozen=True)
class PlacedNode:
    wire: str
    x: float  # centre
    readings: dict[int, NodeReading]


### Latest values ###
def latest_node_readings(
    df: pd.DataFrame, wires: list[str], measurement: str,
) -> dict[str, dict[int, NodeReading]]:
    """Last reading per (wire, height) of ``measurement``.

    A wire or height that never reported is simply absent, never zero-filled.
    ``received_at`` is the relay's insert time (CONTEXT "Reading time"), so
    "latest" is the latest insert, which is as close to "now" as the data gets.
    """
    out: dict[str, dict[int, NodeReading]] = {wire: {} for wire in wires}
    if df.empty:
        return out
    scoped = df[df["measurement"] == measurement].dropna(subset=["value"])
    if scoped.empty:
        return out
    last = scoped.sort_values("time", kind="stable").groupby(["device", "height"]).tail(1)
    for row in last.itertuples():
        wire = _wire_of(row.device)
        height = int(row.height)
        if wire in out and height in WIRE_SENSOR_HEIGHTS:
            out[wire][height] = NodeReading(float(row.value), row.time)
    return out


def _wire_of(device: str) -> str:
    return device.rsplit("-h", 1)[0]


### Placement ###
def place_nodes(
    readings: dict[str, dict[int, NodeReading]], layout: SectionLayout,
) -> list[PlacedNode]:
    """Spread the wires evenly across the greenhouse rectangle.

    Left to right follows ``sorted(readings)``, i.e. wire-id order; the real
    row order is to be confirmed (it may later move to ``metadata.yaml``).
    """
    wires = sorted(readings)
    area = layout.area
    step = area["width"] / max(len(wires), 1)
    return [
        PlacedNode(w, area["x"] + step * (i + 0.5), readings[w])
        for i, w in enumerate(wires)
    ]


### Interpolation ###
def usable(reading: NodeReading | None, style: MeasurementStyle) -> bool:
    """Whether a reading takes part in the interpolation (see ``zero_is_dead``)."""
    if reading is None or reading.stale:
        return False
    return not (style.zero_is_dead and reading.value == 0)


def _grid(layout: SectionLayout, cell_px: float = CELL_PX) -> tuple[np.ndarray, np.ndarray]:
    area = layout.area
    cols = int(np.ceil(area["width"] / cell_px))
    rows = int(np.ceil(area["height"] / cell_px))
    xs = area["x"] + (np.arange(cols) + 0.5) * cell_px
    ys = area["y"] + (np.arange(rows) + 0.5) * cell_px
    return xs, ys


def colour_range(
    nodes: list[PlacedNode], style: MeasurementStyle,
) -> tuple[float, float] | None:
    """One scale across every height, so the vertical gradient reads at a glance."""
    values = [r.value for n in nodes for r in n.readings.values() if usable(r, style)]
    if not values:
        return None
    lo, hi = min(values), max(values)
    pad = (hi - lo) * SCALE_PAD_SHARE
    lo, hi = lo - pad, hi + pad
    if hi - lo < style.min_span:
        mid = (hi + lo) / 2
        lo, hi = mid - style.min_span / 2, mid + style.min_span / 2
    return lo, hi


def interpolate_section(
    nodes: list[PlacedNode],
    layout: SectionLayout,
    style: MeasurementStyle,
    cell_px: float = CELL_PX,
) -> np.ndarray | None:
    """Linear along the wires, linear down the heights.

    Each wire's usable heights are interpolated to every grid row first (a dead
    or missing height is bridged); columns beyond the outer wires take the
    nearest wire's profile. ``None`` when no wire has a usable reading.
    """
    xs, ys = _grid(layout, cell_px)
    profiles = []
    for node in sorted(nodes, key=lambda n: n.x):
        heights = [h for h in sorted(node.readings) if usable(node.readings[h], style)]
        if heights:
            at = [section_y(h, layout) for h in heights]
            profiles.append((node.x, np.interp(ys, at, [node.readings[h].value for h in heights])))
    if not profiles:
        return None
    px = [p[0] for p in profiles]
    field = np.empty((len(ys), len(xs)))
    for r in range(len(ys)):
        field[r] = np.interp(xs, px, [p[1][r] for p in profiles])
    return field


def section_y(height: int, layout: SectionLayout) -> float:
    """Vertical centre of a height's band: H1 at the top, H5 at the bottom."""
    area = layout.area
    index = WIRE_SENSOR_HEIGHTS.index(height)
    return area["y"] + area["height"] * (index + 0.5) / len(WIRE_SENSOR_HEIGHTS)


### Rendering ###
def render_side_svg(
    nodes: list[PlacedNode],
    layout: SectionLayout,
    measurement: str,
    label: str,
    unit: str,
) -> str:
    """Inline SVG: blurred interpolated field, then a column per wire on top."""
    style = MEASUREMENT_STYLES.get(measurement, DEFAULT_STYLE)
    scale = colour_range(nodes, style)
    field, wires = _layers(nodes, layout, style, scale, CELL_PX)
    return _compose(layout, label, unit, style, scale, CELL_PX, [field], [wires])


def render_replay_svg(
    frames: list[list[PlacedNode]],
    layout: SectionLayout,
    measurement: str,
    label: str,
    unit: str,
    scale: tuple[float, float] | None,
    selected: int = 0,
    cell_px: float = REPLAY_CELL_PX,
) -> str:
    """One SVG holding every frame; the chrome and legend are drawn once.

    Each frame is two groups sharing ``data-i`` (its field, and its wire boxes
    above the outline); the browser only toggles which are visible. ``scale`` is
    the one colour scale for the whole window.
    """
    style = MEASUREMENT_STYLES.get(measurement, DEFAULT_STYLE)
    fields, wires = [], []
    for i, nodes in enumerate(frames):
        f, w = _layers(nodes, layout, style, scale, cell_px)
        hidden = "" if i == selected else ' style="display:none"'
        fields.append(f'<g class="rf" data-i="{i}"{hidden}>{f}</g>')
        wires.append(f'<g class="rf" data-i="{i}"{hidden}>{w}</g>')
    return _compose(layout, label, unit, style, scale, cell_px, fields, wires)


def _layers(
    nodes: list[PlacedNode],
    layout: SectionLayout,
    style: MeasurementStyle,
    scale: tuple[float, float] | None,
    cell_px: float,
) -> tuple[str, str]:
    """(interpolated field, wire boxes) for one set of nodes."""
    area = layout.area
    field = interpolate_section(nodes, layout, style, cell_px)
    field_svg = ""
    if field is not None and scale is not None:
        cells = []
        for r, row in enumerate(field):
            for c, value in enumerate(row):
                cells.append(
                    f'<rect x="{area["x"] + c * cell_px:g}" y="{area["y"] + r * cell_px:g}" '
                    f'width="{cell_px + 0.5:g}" height="{cell_px + 0.5:g}" '
                    f'fill="{value_to_color(value, *scale, colorscale=style.colorscale)}"/>'
                )
        field_svg = (
            '<g clip-path="url(#section-clip)"><g filter="url(#section-blur)">'
            + "".join(cells) + "</g></g>"
        )
    return field_svg, "".join(_wire_svg(n, layout, style.decimals) for n in nodes)


def _compose(
    layout: SectionLayout,
    label: str,
    unit: str,
    style: MeasurementStyle,
    scale: tuple[float, float] | None,
    cell_px: float,
    fields: list[str],
    wires: list[str],
) -> str:
    area = layout.area
    parts = [
        f'<svg viewBox="0 0 {layout.width:g} {layout.height:g}" width="100%" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{html.escape(f"Side section of {label} between multi-height wires")}">',
        '<defs>'
        f'<clipPath id="section-clip"><rect x="{area["x"]:g}" y="{area["y"]:g}" '
        f'width="{area["width"]:g}" height="{area["height"]:g}" rx="3"/></clipPath>'
        '<filter id="section-blur" x="-5%" y="-5%" width="110%" height="110%">'
        f'<feGaussianBlur stdDeviation="{cell_px / 2:g}"/></filter>'
        '</defs>',
        f'<rect x="{area["x"]:g}" y="{area["y"]:g}" width="{area["width"]:g}" '
        f'height="{area["height"]:g}" rx="3" fill="#f3f4f6"/>',
        *fields,
        f'<rect x="{area["x"]:g}" y="{area["y"]:g}" width="{area["width"]:g}" '
        f'height="{area["height"]:g}" rx="3" fill="none" stroke="#374151" stroke-width="2"/>',
    ]
    for h in WIRE_SENSOR_HEIGHTS:
        parts.append(
            f'<text x="{area["x"] + 4:g}" y="{section_y(h, layout) + 4:g}" font-size="10" '
            f'fill="#374151">H{h}</text>'
        )
    parts.extend(wires)
    if scale is not None:
        parts.append(_legend_svg(layout, scale, style, unit))
    parts.append("</svg>")
    return "".join(parts)


def _wire_svg(node: PlacedNode, layout: SectionLayout, decimals: int) -> str:
    """The wire as a vertical line joining a boxed value per height."""
    area = layout.area
    x0 = node.x - layout.node_width / 2
    out = [
        f'<line x1="{node.x:g}" y1="{area["y"]:g}" x2="{node.x:g}" '
        f'y2="{area["y"] + area["height"]:g}" stroke="#111827" stroke-width="2"/>',
        f'<text x="{node.x:g}" y="{area["y"] + area["height"] - 3:g}" text-anchor="middle" '
        f'font-size="10" font-weight="700" fill="#111827">{html.escape(node.wire)}</text>',
    ]
    for h in WIRE_SENSOR_HEIGHTS:
        reading = node.readings.get(h)
        text = f"{reading.value:.{decimals}f}" if reading else "—"
        fill, ink = ("#e5e7eb", "#9ca3af") if reading and reading.stale else ("white", "#111827")
        y = section_y(h, layout)
        out.append(
            f'<rect x="{x0:g}" y="{y - BOX_H_PX / 2:g}" width="{layout.node_width:g}" '
            f'height="{BOX_H_PX:g}" rx="4" fill="{fill}" fill-opacity="0.95" '
            'stroke="#111827" stroke-width="1"/>'
            f'<text x="{node.x:g}" y="{y + 4:g}" text-anchor="middle" font-size="12" '
            f'font-weight="700" fill="{ink}">{text}</text>'
        )
    return "".join(out)


def _legend_svg(
    layout: SectionLayout,
    scale: tuple[float, float],
    style: MeasurementStyle,
    unit: str,
) -> str:
    leg = layout.legend

    def colour_at(t: float) -> str:
        value = scale[0] + t * (scale[1] - scale[0])
        return value_to_color(value, *scale, colorscale=style.colorscale)

    stops = "".join(
        f'<stop offset="{t:g}" stop-color="{colour_at(t)}"/>'
        for t in np.linspace(0, 1, 6)
    )
    ty = leg["y"] + leg["height"] + 14
    d = style.decimals
    return (
        f'<defs><linearGradient id="section-legend">{stops}</linearGradient></defs>'
        f'<rect x="{leg["x"]:g}" y="{leg["y"]:g}" width="{leg["width"]:g}" '
        f'height="{leg["height"]:g}" fill="url(#section-legend)" stroke="#9ca3af"/>'
        f'<text x="{leg["x"]:g}" y="{ty:g}" font-size="11" fill="#374151">{scale[0]:.{d}f}</text>'
        f'<text x="{leg["x"] + leg["width"]:g}" y="{ty:g}" text-anchor="end" '
        f'font-size="11" fill="#374151">{scale[1]:.{d}f} {html.escape(unit)}</text>'
    )
