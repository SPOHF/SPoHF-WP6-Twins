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
from ..utils import value_to_color
from .svg import PlanLayout

COLORSCALE = "RdYlBu_r"
CELL_PX = 12
IDW_POWER = 2.0
# A colour scale stretched over a 0.3 °C range would paint noise as a gradient.
MIN_SCALE_SPAN = 2.0
SCALE_PAD = 0.5

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
    """Give each wire (sorted) the next declared slot.

    Wires beyond the declared slots are still drawn, spread along the bottom of
    the area, rather than silently dropped: every installed wire must be seen.
    """
    nodes = []
    wires = sorted(readings)
    extra = wires[len(layout.slots):]
    for wire, slot in zip(wires, layout.slots, strict=False):
        nodes.append(_node(wire, readings[wire], slot["x"], slot["y"],
                           slot["width"], slot["height"]))
    if extra:
        template = layout.slots[-1]
        area = layout.area
        step = area["width"] / (len(extra) + 1)
        y = area["y"] + area["height"] - template["height"] - 8
        for i, wire in enumerate(extra, start=1):
            x = area["x"] + step * i - template["width"] / 2
            nodes.append(_node(wire, readings[wire], x, y,
                               template["width"], template["height"]))
    return nodes


def _node(wire, readings, x, y, width, height) -> PlacedNode:
    return PlacedNode(wire, x + width / 2, y + height / 2, width, height, readings)


### Interpolation ###
def interpolate_field(
    nodes: list[PlacedNode], height: int, layout: PlanLayout,
) -> np.ndarray | None:
    """Inverse-distance-weighted values on a grid of ``CELL_PX`` cells.

    ``None`` when no node reported at ``height``. One node gives a flat field:
    one point says nothing about direction.
    """
    pts = [(n.x, n.y, n.readings[height].value) for n in nodes if height in n.readings]
    if not pts:
        return None
    area = layout.area
    cols = int(np.ceil(area["width"] / CELL_PX))
    rows = int(np.ceil(area["height"] / CELL_PX))
    xs = area["x"] + (np.arange(cols) + 0.5) * CELL_PX
    ys = area["y"] + (np.arange(rows) + 0.5) * CELL_PX
    gx, gy = np.meshgrid(xs, ys)
    px = np.array([p[0] for p in pts])
    py = np.array([p[1] for p in pts])
    pv = np.array([p[2] for p in pts])
    dist = np.hypot(gx[..., None] - px, gy[..., None] - py)
    dist = np.maximum(dist, 1e-6)
    weights = dist ** -IDW_POWER
    return (weights * pv).sum(axis=-1) / weights.sum(axis=-1)


def colour_range(nodes: list[PlacedNode]) -> tuple[float, float] | None:
    """One scale across every height, so switching height shows real change."""
    values = [r.value for n in nodes for r in n.readings.values()]
    if not values:
        return None
    lo, hi = min(values) - SCALE_PAD, max(values) + SCALE_PAD
    if hi - lo < MIN_SCALE_SPAN:
        mid = (hi + lo) / 2
        lo, hi = mid - MIN_SCALE_SPAN / 2, mid + MIN_SCALE_SPAN / 2
    return lo, hi


### Rendering ###
def render_plan_svg(
    nodes: list[PlacedNode],
    layout: PlanLayout,
    height: int,
    unit: str,
    decimals: int = 1,
) -> str:
    """Inline SVG: blurred interpolated field, then a node per wire on top."""
    area = layout.area
    scale = colour_range(nodes)
    field = interpolate_field(nodes, height, layout)
    parts = [
        f'<svg viewBox="0 0 {layout.width:g} {layout.height:g}" width="100%" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Interpolated temperature between multi-height wires">',
        '<defs>'
        f'<clipPath id="plan-clip"><rect x="{area["x"]:g}" y="{area["y"]:g}" '
        f'width="{area["width"]:g}" height="{area["height"]:g}" rx="3"/></clipPath>'
        '<filter id="plan-blur" x="-5%" y="-5%" width="110%" height="110%">'
        f'<feGaussianBlur stdDeviation="{CELL_PX / 2:g}"/></filter>'
        '</defs>',
        f'<rect x="{area["x"]:g}" y="{area["y"]:g}" width="{area["width"]:g}" '
        f'height="{area["height"]:g}" rx="3" fill="#f3f4f6"/>',
    ]
    if field is not None and scale is not None:
        parts.append('<g clip-path="url(#plan-clip)"><g filter="url(#plan-blur)">')
        for r, row in enumerate(field):
            for c, value in enumerate(row):
                parts.append(
                    f'<rect x="{area["x"] + c * CELL_PX:g}" y="{area["y"] + r * CELL_PX:g}" '
                    f'width="{CELL_PX + 0.5:g}" height="{CELL_PX + 0.5:g}" '
                    f'fill="{value_to_color(value, *scale, colorscale=COLORSCALE)}"/>'
                )
        parts.append("</g></g>")
    parts.append(
        f'<rect x="{area["x"]:g}" y="{area["y"]:g}" width="{area["width"]:g}" '
        f'height="{area["height"]:g}" rx="3" fill="none" stroke="#374151" stroke-width="2"/>'
    )
    parts.extend(_node_svg(n, height, decimals) for n in nodes)
    if scale is not None:
        parts.append(_legend_svg(layout, scale, unit, height))
    parts.append("</svg>")
    return "".join(parts)


def _node_svg(node: PlacedNode, selected: int, decimals: int) -> str:
    x0, y0 = node.x - node.width / 2, node.y - node.height / 2
    row_h = (node.height - NODE_HEADER_PX - NODE_ROW_PAD_PX) / len(WIRE_SENSOR_HEIGHTS)
    out = [
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


def _legend_svg(layout: PlanLayout, scale: tuple[float, float], unit: str, height: int) -> str:
    leg = layout.legend
    def colour_at(t: float) -> str:
        value = scale[0] + t * (scale[1] - scale[0])
        return value_to_color(value, *scale, colorscale=COLORSCALE)

    stops = "".join(
        f'<stop offset="{t:g}" stop-color="{colour_at(t)}"/>'
        for t in np.linspace(0, 1, 6)
    )
    ty = leg["y"] + leg["height"] + 14
    return (
        f'<defs><linearGradient id="plan-legend">{stops}</linearGradient></defs>'
        f'<rect x="{leg["x"]:g}" y="{leg["y"]:g}" width="{leg["width"]:g}" '
        f'height="{leg["height"]:g}" fill="url(#plan-legend)" stroke="#9ca3af"/>'
        f'<text x="{leg["x"]:g}" y="{ty:g}" font-size="11" fill="#374151">{scale[0]:.1f}</text>'
        f'<text x="{leg["x"] + leg["width"]:g}" y="{ty:g}" text-anchor="end" '
        f'font-size="11" fill="#374151">{scale[1]:.1f} {html.escape(unit)}</text>'
        f'<text x="{leg["x"] + leg["width"] / 2:g}" y="{ty:g}" text-anchor="middle" '
        f'font-size="11" fill="#374151">field at H{height}</text>'
    )
