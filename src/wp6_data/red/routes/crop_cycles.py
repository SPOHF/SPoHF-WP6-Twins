"""The red "Crop cycles" page: overlapping fruit cohorts as a waterfall.

One lane per fruit cohort, staggered diagonally across the season, so a vertical
slice at any date shows the cohorts that were in flight. The chosen climate
metric is painted *onto* those bars day by day, and each cohort carries its
Sijia measurement written inside its own bar — so a spell of weather and the
fruit that lived through it are the same mark on the page, not two rows to
compare by eye.

Every declared crop cycle is drawn at once, grouped and labelled in the margin.
The cycles are consecutive seasons of the same greenhouse rather than
alternatives, so making the reader pick one hid the comparison the page exists
to support.

Selection is all GET params so the view stays bookmarkable, matching the rest of
red. Deliberately no correlation statistics: with roughly a dozen usable
observations, a coefficient would imply far more than the data supports.
"""

from __future__ import annotations

import html
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_card, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider
from wp6_data.shared.waterfall import (
    VALUE_SCALE,
    render_waterfall,
    series_colors,
    value_range,
)

from .. import deps
from ..crop_cycles.config import load_crop_cycles
from ..crop_cycles.view_model import assemble_waterfall
from ..multi_height.cells import pill_row

router = APIRouter(prefix="/crop-cycles", dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "Crop Cycles"
MANUAL_SOURCE = "sijia"

def _measure_choices() -> list[tuple[str, str]]:
    """Selectable fruit measures, enumerated from metadata rather than hardcoded."""
    return [
        (tag, meta.alias or tag.replace("_", " ").title())
        for tag, meta in sorted(deps.metadata.sensor_defaults.items())
        if meta.source == MANUAL_SOURCE
    ]


def _measure_devices() -> dict[str, str]:
    """Manual-measurement devices mapped to a short display label."""
    devices = {}
    for device_id, meta in sorted(deps.metadata.devices.items()):
        if meta.source != MANUAL_SOURCE:
            continue
        # "Strabelina cultivar at row 2034" -> "Strabelina"
        devices[device_id] = (meta.description or device_id).split(" cultivar")[0]
    return devices


def _note(text: str, color: str = "#6b7280") -> str:
    return f'<p style="color:{color};margin:0.35rem 0 0;font-size:0.85rem;">{text}</p>'


def _value_key(lanes, measure_label: str) -> str:
    """Decode the two things a value chip encodes: its fill and its outline.

    The chart cannot legend them itself — the chips are annotations, not traces —
    and both the colours and the range come straight from ``shared.waterfall``,
    so this can never drift out of step with what was drawn.
    """
    span = value_range(lanes)
    if span is None:
        return ""

    low, high = span
    gradient = ", ".join(VALUE_SCALE)
    parts = [
        f'<span style="display:inline-flex;align-items:center;gap:0.4rem;">'
        f"{html.escape(measure_label)} {low:g}"
        f'<span style="width:3rem;height:0.6rem;border-radius:2px;'
        f'background:linear-gradient(to right, {gradient});"></span>'
        f"{high:g}</span>"
    ]

    colors = series_colors(lanes)
    if len(colors) > 1:  # a single cultivar needs no telling apart
        outlines = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:0.3rem;">'
            f'<span style="width:0.6rem;height:0.6rem;border-radius:2px;'
            f'border:1.5px solid {color};"></span>{html.escape(name)}</span>'
            for name, color in colors.items()
        )
        parts.append(
            f'<span style="display:inline-flex;align-items:center;gap:0.6rem;">'
            f"Outline: {outlines}</span>"
        )

    return (
        '<p style="color:#6b7280;margin:0.35rem 0 0;font-size:0.85rem;'
        'display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap;">'
        f'{"".join(parts)}</p>'
    )


@router.get("/", response_class=HTMLResponse)
async def crop_cycles_page(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    measure: Annotated[
        str | None, Query(description="Fruit measure shown at each cohort's harvest")
    ] = None,
    climate: Annotated[
        str | None, Query(description="Climate metric painted onto the bars")
    ] = None,
    variety: Annotated[
        str | None, Query(description="Cultivar to show, or 'both'")
    ] = None,
) -> str:
    timezone = deps.base_settings.display_timezone
    config = load_crop_cycles(deps._METADATA_PATH)

    measures = _measure_choices()
    all_devices = _measure_devices()

    metric = config.metric(climate or "")
    measure = measure if any(measure == t for t, _ in measures) else (
        "brix" if any(t == "brix" for t, _ in measures) else measures[0][0]
    )
    variety = variety if variety in {*all_devices, "both"} else "both"
    devices = all_devices if variety == "both" else {variety: all_devices[variety]}

    view = await assemble_waterfall(
        provider, config, config.cycles, metric, measure, devices, timezone,
    )

    measure_label = dict(measures).get(measure, measure)
    chart = render_waterfall(
        view.lanes,
        view.daily,
        series_label=f"{metric.label} ({metric.unit})",
        marker_label=measure_label,
    )

    if chart is None:
        body = _note("No cohorts fit inside any declared crop cycle — check "
                     "their dates.")
    else:
        body = chart

    # Say plainly what the picture cannot: which lanes rest on partial climate,
    # and which measurements landed outside every cohort (the signal that the
    # declared cycle dates are wrong).
    notes = []
    if view.lanes:
        notes.append(
            f"{len(view.measured)} of {len(view.lanes)} cohorts carry a "
            f"{html.escape(measure_label)} measurement."
        )
    if view.partial:
        notes.append(
            f"{len(view.partial)} cohort(s) show gaps: their development window "
            f"is only partly covered by {html.escape(metric.label.lower())} data."
        )
    if view.unattached:
        days = ", ".join(sorted({str(u.day) for u in view.unattached}))
        notes.append(
            f"⚠ {len(view.unattached)} measurement(s) fell outside every cohort "
            f"({html.escape(days)}) — the declared cycle dates are likely wrong."
        )

    others = {"climate": metric.key, "measure": measure, "variety": variety}

    def _pills(param, choices, active, label):
        return pill_row(
            "/crop-cycles/", param, choices, active,
            {k: v for k, v in others.items() if k != param}, label,
        )

    controls = (
        _pills("climate", [(m.key, m.label) for m in config.climate.metrics],
               metric.key, "Climate")
        + _pills("measure", measures, measure, "Measure")
        + _pills("variety",
                 [("both", "Both"), *all_devices.items()], variety, "Cultivar")
    )

    content = f"""
    <a href="/" class="back-link">← Dashboard</a>
    <h1>{PAGE_TITLE}</h1>
    <p>A new truss sets each week and ripens over about eight weeks, so several
    cohorts are always in flight. Each lane is one cohort, coloured by the
    {html.escape(metric.label.lower())} it lived through; read a vertical slice
    to see which cohorts met a given spell of weather, and how their fruit
    turned out.</p>
    {controls}
    {render_card(
        f"Cohorts against {html.escape(metric.label.lower())}",
        body + _value_key(view.lanes, measure_label)
             + "".join(_note(n) for n in notes),
        description=f"Bar colour is {html.escape(metric.label.lower())} on the "
                    f"day; a gap is a day that reported nothing. The chip at "
                    f"a bar's end is its {html.escape(measure_label)} at harvest, "
                    "filled by how it compares with the rest; a bar with no chip "
                    "was never sampled.",
        card_class="card",
    )}
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)
