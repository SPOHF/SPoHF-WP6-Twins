"""Plan-view view-model and renderer for the red multi-height wires.

Shows the *latest* reading of every installed **Multi-height wire** on one
schematic of the greenhouse: each wire is a node listing its five heights, and
the rest of the canvas is a field interpolated between the nodes for one chosen
height. Pure (no I/O) like :mod:`.uniformity`, so it is testable without a
database; the route only fetches readings and hands them in.

Wire positions are not known (only "a few metres apart"), so nodes sit in the
slots declared in ``static/multi_height_plan.svg`` and the field is a schematic,
not a survey. Interpolation is inverse-distance weighting: it never exceeds the
readings it was given, which a smoother scheme would, between so few points.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from ..db import WIRE_SENSOR_HEIGHTS
from ..utils import PAR_COLORSCALE, value_to_color
from .svg import PlanLayout


@dataclass(frozen=True)
class MeasurementStyle:
    """Colour scale, narrowest range it may be stretched over, decimals shown.

    The minimum span keeps a near-constant reading from being painted as a
    gradient (e.g. 0.3 °C of noise).
    """

    colorscale: object
    min_span: float
    decimals: int


MEASUREMENT_STYLES = {
    "par": MeasurementStyle(PAR_COLORSCALE, 50.0, 0),
    "temp": MeasurementStyle("RdYlBu_r", 2.0, 1),
    "hum": MeasurementStyle("YlGnBu", 5.0, 1),
    "co2": MeasurementStyle("Purples", 50.0, 0),
}
DEFAULT_STYLE = MEASUREMENT_STYLES["temp"]
CELL_PX = 12
SCALE_PAD_SHARE = 0.05
BOX_H_PX = 18

NODE_HEADER_PX = 20
NODE_ROW_PAD_PX = 6


@dataclass(frozen=True)
class NodeReading:
    value: float
    time: pd.Timestamp


@dataclass(frozen=True)
class PlacedNode:
    wire: str
    x: float  # centre
    y: float
    width: float
    height: float
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
    readings: dict[str, dict[int, NodeReading]], layout: PlanLayout,
) -> list[PlacedNode]:
    """Spread the wires (sorted) evenly across the greenhouse rectangle.

    Positions are unknown, so equal spacing is the neutral choice. The first
    slot only supplies the node size and its vertical position.
    """
    wires = sorted(readings)
    slot = layout.slots[0]
    area = layout.area
    step = area["width"] / max(len(wires), 1)
    return [
        _node(w, readings[w], area["x"] + step * (i + 0.5) - slot["width"] / 2,
              slot["y"], slot["width"], slot["height"])
        for i, w in enumerate(wires)
    ]


def _node(wire, readings, x, y, width, height) -> PlacedNode:
    return PlacedNode(wire, x + width / 2, y + height / 2, width, height, readings)


### Interpolation ###
def usable(reading: NodeReading | None) -> bool:
    """A reading of exactly 0 is a dead sensor: shown, but never interpolated."""
    return reading is not None and reading.value != 0


def _grid(layout: PlanLayout) -> tuple[np.ndarray, np.ndarray]:
    area = layout.area
    cols = int(np.ceil(area["width"] / CELL_PX))
    rows = int(np.ceil(area["height"] / CELL_PX))
    xs = area["x"] + (np.arange(cols) + 0.5) * CELL_PX
    ys = area["y"] + (np.arange(rows) + 0.5) * CELL_PX
    return xs, ys


def interpolate_field(
    nodes: list[PlacedNode], height: int, layout: PlanLayout,
) -> np.ndarray | None:
    """Field of one height: linear between the wires that report it.

    Each height is interpolated on its own; wires with no usable reading there
    are skipped. ``None`` when no wire has one. Outside the outer wires the
    nearest value holds.
    """
    pts = sorted(
        (n.x, n.readings[height].value) for n in nodes if usable(n.readings.get(height))
    )
    if not pts:
        return None
    xs, ys = _grid(layout)
    row = np.interp(xs, [p[0] for p in pts], [p[1] for p in pts])
    return np.tile(row, (len(ys), 1))


def colour_range(nodes: list[PlacedNode], style: MeasurementStyle) -> tuple[float, float] | None:
    """One scale across every height, so switching height shows real change."""
    values = [r.value for n in nodes for r in n.readings.values() if usable(r)]
    if not values:
        return None
    lo, hi = min(values), max(values)
    pad = (hi - lo) * SCALE_PAD_SHARE
    lo, hi = lo - pad, hi + pad
    if hi - lo < style.min_span:
        mid = (hi + lo) / 2
        lo, hi = mid - style.min_span / 2, mid + style.min_span / 2
    return lo, hi


def interpolate_section(nodes: list[PlacedNode], layout: PlanLayout) -> np.ndarray | None:
    """Side-section field: linear along the wires, linear down the heights.

    Each wire's usable heights are interpolated to every grid row first (a dead
    or missing height is bridged); columns beyond the outer wires take the
    nearest wire's profile. ``None`` when no wire has a usable reading.
    """
    xs, ys = _grid(layout)
    profiles = []
    for node in sorted(nodes, key=lambda n: n.x):
        heights = [h for h in sorted(node.readings) if usable(node.readings[h])]
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

def section_y(height: int, layout: PlanLayout) -> float:
    """Vertical centre of a height's band: H1 at the top, H5 at the bottom."""
    area = layout.area
    index = WIRE_SENSOR_HEIGHTS.index(height)
    return area["y"] + area["height"] * (index + 0.5) / len(WIRE_SENSOR_HEIGHTS)


### Rendering ###
def render_plan_svg(
    nodes: list[PlacedNode],
    layout: PlanLayout,
    height: int,
    measurement: str,
    label: str,
    unit: str,
) -> str:
    """Inline SVG: blurred interpolated field, then a node per wire on top."""
    style = MEASUREMENT_STYLES.get(measurement, DEFAULT_STYLE)
    scale = colour_range(nodes, style)
    field = interpolate_field(nodes, height, layout)
    parts = _canvas_open(layout, f"Interpolated {label} between multi-height wires")
    parts.extend(_field_svg(field, scale, style, layout))
    parts.extend(_node_svg(n, height, style.decimals, layout) for n in nodes)
    if scale is not None:
        parts.append(_legend_svg(layout, scale, style, unit, f"field at H{height}"))
    parts.append("</svg>")
    return "".join(parts)


def render_side_svg(
    nodes: list[PlacedNode],
    layout: PlanLayout,
    measurement: str,
    label: str,
    unit: str,
) -> str:
    """Inline SVG side section: heights run top (H1) to bottom (H5)."""
    style = MEASUREMENT_STYLES.get(measurement, DEFAULT_STYLE)
    scale = colour_range(nodes, style)
    field = interpolate_section(nodes, layout)
    parts = _canvas_open(layout, f"Side section of {label} between multi-height wires")
    parts.extend(_field_svg(field, scale, style, layout))
    area = layout.area
    for h in WIRE_SENSOR_HEIGHTS:
        y = section_y(h, layout)
        parts.append(
            f'<text x="{area["x"] + 4:g}" y="{y + 4:g}" font-size="10" '
            f'fill="#374151">H{h}</text>'
        )
    for node in nodes:
        parts.append(_section_node_svg(node, layout, style.decimals))
    if scale is not None:
        parts.append(_legend_svg(layout, scale, style, unit, "side section"))
    parts.append("</svg>")
    return "".join(parts)


def _canvas_open(layout: PlanLayout, aria_label: str) -> list[str]:
    area = layout.area
    return [
        f'<svg viewBox="0 0 {layout.width:g} {layout.height:g}" width="100%" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{html.escape(aria_label)}">',
        '<defs>'
        f'<clipPath id="plan-clip"><rect x="{area["x"]:g}" y="{area["y"]:g}" '
        f'width="{area["width"]:g}" height="{area["height"]:g}" rx="3"/></clipPath>'
        '<filter id="plan-blur" x="-5%" y="-5%" width="110%" height="110%">'
        f'<feGaussianBlur stdDeviation="{CELL_PX / 2:g}"/></filter>'
        '</defs>',
        f'<rect x="{area["x"]:g}" y="{area["y"]:g}" width="{area["width"]:g}" '
        f'height="{area["height"]:g}" rx="3" fill="#f3f4f6"/>',
    ]


def _field_svg(
    field: np.ndarray | None,
    scale: tuple[float, float] | None,
    style: MeasurementStyle,
    layout: PlanLayout,
) -> list[str]:
    area = layout.area
    parts = []
    if field is not None and scale is not None:
        parts.append('<g clip-path="url(#plan-clip)"><g filter="url(#plan-blur)">')
        for r, row in enumerate(field):
            for c, value in enumerate(row):
                parts.append(
                    f'<rect x="{area["x"] + c * CELL_PX:g}" y="{area["y"] + r * CELL_PX:g}" '
                    f'width="{CELL_PX + 0.5:g}" height="{CELL_PX + 0.5:g}" '
                    f'fill="{value_to_color(value, *scale, colorscale=style.colorscale)}"/>'
                )
        parts.append("</g></g>")
    parts.append(
        f'<rect x="{area["x"]:g}" y="{area["y"]:g}" width="{area["width"]:g}" '
        f'height="{area["height"]:g}" rx="3" fill="none" stroke="#374151" stroke-width="2"/>'
    )
    return parts


def _wire_line(node: PlacedNode, layout: PlanLayout) -> str:
    """The wire itself: one vertical line joining all sensors of a node."""
    area = layout.area
    return (
        f'<line x1="{node.x:g}" y1="{area["y"]:g}" x2="{node.x:g}" '
        f'y2="{area["y"] + area["height"]:g}" stroke="#111827" stroke-width="2"/>'
    )


def _section_node_svg(node: PlacedNode, layout: PlanLayout, decimals: int) -> str:
    x0 = node.x - node.width / 2
    area = layout.area
    out = [
        _wire_line(node, layout),
        f'<text x="{node.x:g}" y="{area["y"] + area["height"] - 3:g}" text-anchor="middle" '
        f'font-size="10" font-weight="700" fill="#111827">{html.escape(node.wire)}</text>'
    ]
    for h in WIRE_SENSOR_HEIGHTS:
        reading = node.readings.get(h)
        text = f"{reading.value:.{decimals}f}" if reading else "—"
        y = section_y(h, layout)
        out.append(
            f'<rect x="{x0:g}" y="{y - BOX_H_PX / 2:g}" width="{node.width:g}" '
            f'height="{BOX_H_PX:g}" rx="4" fill="white" fill-opacity="0.95" '
            'stroke="#111827" stroke-width="1"/>'
            f'<text x="{node.x:g}" y="{y + 4:g}" text-anchor="middle" font-size="12" '
            f'font-weight="700" fill="#111827">{text}</text>'
        )
    return "".join(out)


def _node_svg(node: PlacedNode, selected: int, decimals: int, layout: PlanLayout) -> str:
    x0, y0 = node.x - node.width / 2, node.y - node.height / 2
    row_h = (node.height - NODE_HEADER_PX - NODE_ROW_PAD_PX) / len(WIRE_SENSOR_HEIGHTS)
    out = [
        _wire_line(node, layout),
        f'<rect x="{x0:g}" y="{y0:g}" width="{node.width:g}" height="{node.height:g}" '
        'rx="6" fill="white" fill-opacity="0.95" stroke="#111827" stroke-width="1.5"/>',
        f'<text x="{node.x:g}" y="{y0 + 14:g}" text-anchor="middle" font-size="11" '
        f'font-weight="700" fill="#111827">{html.escape(node.wire)}</text>',
    ]
    for i, h in enumerate(WIRE_SENSOR_HEIGHTS):
        y = y0 + NODE_HEADER_PX + row_h * (i + 0.5) + 4
        reading = node.readings.get(h)
        text = f"{reading.value:.{decimals}f}" if reading else "—"
        is_sel = h == selected
        if is_sel:
            out.append(
                f'<rect x="{x0 + 3:g}" y="{y - row_h / 2 - 2:g}" width="{node.width - 6:g}" '
                f'height="{row_h:g}" rx="3" fill="#fee2e2"/>'
            )
        out.append(
            f'<text x="{x0 + 8:g}" y="{y:g}" font-size="9" fill="#6b7280">H{h}</text>'
            f'<text x="{x0 + node.width - 8:g}" y="{y:g}" text-anchor="end" font-size="12" '
            f'font-weight="{700 if is_sel else 400}" fill="#111827">{text}</text>'
        )
    return "".join(out)


def _legend_svg(
    layout: PlanLayout,
    scale: tuple[float, float],
    style: MeasurementStyle,
    unit: str,
    caption: str,
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
        f'<defs><linearGradient id="plan-legend">{stops}</linearGradient></defs>'
        f'<rect x="{leg["x"]:g}" y="{leg["y"]:g}" width="{leg["width"]:g}" '
        f'height="{leg["height"]:g}" fill="url(#plan-legend)" stroke="#9ca3af"/>'
        f'<text x="{leg["x"]:g}" y="{ty:g}" font-size="11" fill="#374151">{scale[0]:.{d}f}</text>'
        f'<text x="{leg["x"] + leg["width"]:g}" y="{ty:g}" text-anchor="end" '
        f'font-size="11" fill="#374151">{scale[1]:.{d}f} {html.escape(unit)}</text>'
        f'<text x="{leg["x"] + leg["width"] / 2:g}" y="{ty:g}" text-anchor="middle" '
        f'font-size="11" fill="#374151">{html.escape(caption)}</text>'
    )
