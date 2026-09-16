"""GET /climate/forecast — the crop as it will stand, section by section.

The grower-facing counterpart to the admin ``/climate/model`` diagnostics. It
shows the vertical profile at each fitted horizon rather than a curve through
time, because those horizons are what the chain was actually fitted and scored
at (see ``climate/charts.py``).

Every number on the chart also appears in the table beneath it: that is the
accessible view, and it is the relief the lightest ramp step's contrast
obliges.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.climate import data as climate_data
from wp6_data.red.climate.charts import (
    forecast_band_chart,
    forecast_profile_chart,
    select_profiles,
    typical_uncertainty,
)
from wp6_data.red.climate.config import load_climate_model
from wp6_data.red.climate.forecast import (
    MEASUREMENT_LABELS,
    ForecastView,
    build_forecast,
)
from wp6_data.red.climate.training import load_models
from wp6_data.shared import pill_row, render_card, render_page, render_table
from wp6_data.shared.auth import verify_session_user

router = APIRouter(
    prefix="/climate", dependencies=[Depends(verify_session_user)]
)

PAGE_TITLE = "SPoHF Red - Climate Forecast"
BASE_PATH = "/climate/forecast"

# The forecast is reached from the Multi Height hub, so it links back there.
# Written out rather than using render_page's back link, which always reads
# "Home" whatever URL it points at — the same reason crop-climate rolls its own.
BACK_LINK = '<a href="/multi_height" class="back-link">&larr; Multi Height</a>' 


def _message_page(body: str) -> str:
    return render_page(
        PAGE_TITLE, BACK_LINK + render_card("Forecast unavailable", body)
    )


# Beyond this many horizons, listing each one is a wall of near-identical
# numbers rather than information — the spread plateaus after a few hours.
UNCERTAINTY_DETAIL_LIMIT = 6


def _uncertainty_note(spreads: list[tuple[str, float]], unit: str) -> str:
    """State the ± per horizon, or summarise it once the list stops informing.

    Combined error is dominated by link 2, so at a given horizon every section
    carries almost the same spread — which is why it is stated once per horizon
    rather than drawn as five nearly identical error ranges. With a dense set of
    horizons the per-horizon figures plateau, so beyond a handful the range is
    more useful than the roll-call; the exact figure for any point stays on its
    hover, and per-section figures are in the table.
    """
    if not spreads:
        return ""
    if len(spreads) <= UNCERTAINTY_DETAIL_LIMIT:
        detail = " · ".join(f"{label} ± {spread:g}" for label, spread in spreads)
    else:
        nearest_label, nearest = spreads[0]
        widest_label, widest = max(spreads, key=lambda pair: pair[1])
        detail = (
            f"± {nearest:g} at {nearest_label}, widening to "
            f"± {widest:g} by {widest_label} and roughly flat after"
        )
    return (
        f"<p class='muted'>Typical held-out spread ({unit}): {detail}. "
        f"Per-point figures are on hover; per-section figures in the table "
        f"below.</p>"
    )


def _profile_table(view: ForecastView, timezone: str) -> str:
    """The same numbers as the chart, as text.

    Not a fallback — the table is how the forecast is read precisely, and how it
    is read at all without colour.
    """
    tz = ZoneInfo(timezone)
    now = [view.now] if view.now and view.now.points else []
    drawn = now + select_profiles([s for s in view.predicted if s.points])
    headers = ["Growth section", *[
        f"{s.clock(tz)} ({s.label})" for s in drawn
    ]]
    heights = sorted({p.height for s in drawn for p in s.points})
    labels = {p.height: p.label for s in drawn for p in s.points}

    rows = []
    for height in heights:
        cells = [f"H{height} {labels.get(height, '')}".strip()]
        for snapshot in drawn:
            point = next((p for p in snapshot.points if p.height == height), None)
            if point is None:
                cells.append("—")
            elif point.uncertainty is None:
                cells.append(f"{point.value:g} {view.unit}")
            else:
                cells.append(f"{point.value:g} ± {point.uncertainty:g}")
        rows.append(cells)
    return render_table(headers, rows, sortable=False)


@router.get("/forecast", response_class=HTMLResponse)
async def climate_forecast(
    wire: str = Query(default=""),
    measure: str = Query(default="temp"),
) -> str:
    """The predicted vertical profile for one wire and measurement."""
    if not climate_data.is_connected():
        return _message_page("<p>Database not connected.</p>")

    config = load_climate_model(deps._METADATA_PATH)
    loaded = load_models(config)
    if loaded is None:
        return _message_page(
            "<p>No climate model has been trained yet. The model lives on "
            "ephemeral storage and is retrained on boot; an admin can also "
            "train it from <a href='/climate/model/'>the model page</a>.</p>"
        )
    chain, model, downscaler = loaded

    wires = config.wires_reporting(measure)
    if not wires:
        return _message_page(
            f"<p>No wire reports {measure}. See "
            f"<code>climate_model.wire_availability</code>.</p>"
        )
    wire = wire if wire in wires else wires[0]

    sections = {s.height: s.label for s in deps.growth_sections}
    view = await build_forecast(
        config, chain, model, downscaler, deps.get_weather_client(),
        wire=wire, measurement=measure, sections=sections,
    )

    measures = [
        (key, MEASUREMENT_LABELS.get(key, key))
        for key in ("temp", "hum", "co2", "par")
        if config.wires_reporting(key)
    ]
    controls = (
        pill_row(BASE_PATH, "measure", measures, measure, {"wire": wire}, "Measurement")
        + pill_row(
            BASE_PATH, "wire", [(w, w) for w in wires], wire,
            {"measure": measure}, "Wire",
        )
    )

    timezone = deps.base_settings.display_timezone
    band = forecast_band_chart(view, timezone)
    spreads = typical_uncertainty(view)
    chart = forecast_profile_chart(view)
    notes = "".join(f"<p class='muted'>{note}</p>" for note in view.notes)
    if chart is None:
        return render_page(
            PAGE_TITLE,
            BACK_LINK + f"<h1>Climate forecast</h1>{controls}"
            + render_card(
                "Nothing to draw",
                notes or "<p>No prediction is available for this selection.</p>",
            ),
        )

    weak = [s for s in view.predicted if s.beats_persistence is False]
    caveat = ""
    if weak:
        horizons = ", ".join(f"+{s.horizon_hours} h" for s in weak)
        caveat = (
            f"<p class='muted'>At {horizons} the model does not beat simply "
            f"using the current reading, and is drawn dotted.</p>"
        )

    content = f"""
        {BACK_LINK}
        <h1>Climate forecast</h1>
        <p class="muted">{MEASUREMENT_LABELS.get(measure, measure)} on {wire},
        by growth section. Reference: {view.reference_key}.
        Issued {view.issued_at:%Y-%m-%d %H:%M} UTC.</p>
        {controls}
        {render_card(
            f"{MEASUREMENT_LABELS.get(measure, measure)} ahead",
            band + _uncertainty_note(spreads, view.unit) + (
                "<p class='muted'>Measured values are drawn at the sensors' "
                "own cadence; the forecast shows only the horizons the model "
                "was fitted at, so the dashes between those markers are drawn, "
                "not predicted.</p>"
            ),
            description=(
                "Every growth section over time, inside the shaded envelope "
                "of the crop — so the width of the shading is the vertical "
                "gradient. Solid is measured, dashed is forecast, and the grey "
                "line is outdoors."
            ),
        ) if band else ""}
        {render_card(
            "Profile down the crop",
            chart + caveat + notes,
            description=(
                "Each profile is a horizon the chain was actually fitted and "
                "scored at — not a curve through time. Bars show the two links' "
                "combined held-out error at that horizon and height: a measured "
                "spread, not a confidence interval."
            ),
        )}
        {render_card(
            "The same numbers",
            _profile_table(view, timezone),
            description="Value ± combined held-out RMSE, in {unit}.".format(
                unit=view.unit or "the measurement's units"
            ),
        )}
        <p class="muted">How well this model does, horizon by horizon, is on
        <a href="/climate/model/">the model page</a>.</p>
    """
    return render_page(PAGE_TITLE, content)
