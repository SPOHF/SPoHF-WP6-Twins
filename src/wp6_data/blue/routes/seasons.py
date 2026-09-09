"""GET /seasons — blue's treatments over the weather they grew in.

One lane per treatment per growing season, painted day by day with the chosen
weather metric and carrying that treatment's outcome on a chip at the season's
end. Where red's crop-cycles page reads *diagonally* — several cohorts in flight
at once — this one reads *vertically*: nine plots that lived through one
weather, and how their fruit differed.

A top-level blue feature with its own home-page card, like the GDD tracker, so
it self-guards auth rather than inheriting it from the monitor router.

Selection is all GET params so the view stays bookmarkable, matching the rest of
the platform. Deliberately no significance testing: nine plots and a handful of
seasons would not support a claim that one treatment beat another.
"""

from __future__ import annotations

import html
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.config import Settings
from wp6_data.shared import pill_row, render_card, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider
from wp6_data.shared.waterfall import VALUE_SCALE, render_waterfall, value_range

from .. import deps
from ..seasons.config import load_seasons
from ..seasons.view_model import assemble_seasons
from ..treatments import TREATMENT_ORDER

router = APIRouter(prefix="/seasons", dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "Seasons"
MANUAL_SOURCE = "long_data"

settings = Settings()


def _measure_choices() -> list[tuple[str, str]]:
    """Selectable measures, enumerated from metadata rather than hardcoded."""
    return [
        (tag, meta.alias or tag.replace("_", " ").title())
        for tag, meta in sorted(deps.metadata.sensor_defaults.items())
        if meta.source == MANUAL_SOURCE
    ]


def _treatments() -> dict[str, str]:
    """Treatment devices in the canonical display order, from metadata."""
    declared = {
        device
        for device, meta in deps.metadata.devices.items()
        if meta.source == MANUAL_SOURCE
    }
    # TREATMENT_ORDER keeps comparable strategies adjacent; anything declared in
    # metadata but missing from that order still gets a lane rather than
    # vanishing silently.
    ordered = [t for t in TREATMENT_ORDER if t in declared]
    return {t: t for t in ordered + sorted(declared - set(ordered))}


def _note(text: str, color: str = "#6b7280") -> str:
    return f'<p style="color:{color};margin:0.35rem 0 0;font-size:0.85rem;">{text}</p>'


def _value_key(lanes, measure_label: str) -> str:
    """A gradient strip decoding the chip fill, using the drawn colours."""
    span = value_range(lanes)
    if span is None:
        return ""
    low, high = span
    gradient = ", ".join(VALUE_SCALE)
    return (
        '<p style="color:#6b7280;margin:0.35rem 0 0;font-size:0.85rem;'
        'display:flex;gap:0.4rem;align-items:center;flex-wrap:wrap;">'
        f"{html.escape(measure_label)} {low:g}"
        f'<span style="width:3rem;height:0.6rem;border-radius:2px;'
        f'background:linear-gradient(to right, {gradient});"></span>'
        f"{high:g}</p>"
    )


@router.get("/", response_class=HTMLResponse)
async def seasons_page(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    measure: Annotated[
        str | None, Query(description="Measure shown at each treatment's season end")
    ] = None,
    weather: Annotated[
        str | None, Query(description="Weather metric painted onto the bars")
    ] = None,
) -> str:
    timezone = settings.display_timezone
    config = load_seasons(deps.METADATA_PATH)

    measures = _measure_choices()
    treatments = _treatments()

    metric = config.metric(weather or "")
    measure = measure if any(measure == t for t, _ in measures) else (
        "brix" if any(t == "brix" for t, _ in measures) else measures[0][0]
    )
    measure_label = dict(measures).get(measure, measure)
    # How repeat samples of a treatment combine over a season is the measure's
    # own business, declared beside its unit and alias. Two levels: within one
    # harvest pass, then across the season's passes.
    declared = deps.metadata.sensor_defaults[measure]

    view = await assemble_seasons(
        provider, config, metric, measure, treatments, timezone,
        measure_agg=declared.agg,
        measure_period_agg=declared.period_agg,
    )

    chart = render_waterfall(
        view.lanes,
        view.daily,
        series_label=f"{metric.label} ({metric.unit})",
        marker_label=measure_label,
    )
    body = chart if chart is not None else _note(
        "No seasons are declared — check the metadata block."
    )

    notes = []
    if view.lanes:
        notes.append(
            f"{len(view.measured)} of {len(view.lanes)} treatment-seasons carry a "
            f"{html.escape(measure_label)} measurement."
        )
    if view.partial:
        notes.append(
            f"{len(view.partial)} of {len(view.lanes)} show gaps: their season "
            f"is only partly covered by {html.escape(metric.label.lower())} data."
        )
    if view.unattached:
        days = ", ".join(sorted({str(u.day) for u in view.unattached})[:6])
        notes.append(
            f"⚠ {len(view.unattached)} measurement(s) fell outside every declared "
            f"season ({html.escape(days)}) — the season dates are likely wrong."
        )

    others = {"weather": metric.key, "measure": measure}

    def _pills(param, choices, active, label):
        return pill_row(
            "/seasons/", param, choices, active,
            {k: v for k, v in others.items() if k != param}, label,
        )

    controls = (
        _pills("weather", [(m.key, m.label) for m in config.weather.metrics],
               metric.key, "Weather")
        + _pills("measure", measures, measure, "Measure")
    )

    content = f"""
    <a href="/" class="back-link">← Dashboard</a>
    <h1>{PAGE_TITLE}</h1>
    <p>Every treatment is measured over the same season, so the lanes stack
    rather than stagger: read across a season to compare plots that lived
    through one {html.escape(metric.label.lower())}, and down the groups to
    compare one plot's years.</p>
    {controls}
    {render_card(
        f"Treatments against {html.escape(metric.label.lower())}",
        body + _value_key(view.lanes, measure_label)
             + "".join(_note(n) for n in notes),
        description=f"Bar colour is {html.escape(metric.label.lower())} on the "
                    f"day; a gap is a day that reported nothing. The chip at a "
                    f"bar's end is that treatment's {html.escape(measure_label)} "
                    "for the season, filled by how it compares with the rest; a "
                    "bar with no chip was never sampled.",
        card_class="card",
    )}
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)
