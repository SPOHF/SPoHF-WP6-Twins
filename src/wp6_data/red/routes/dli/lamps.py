"""GET /dli/lamps — When the lamps are on, as a date × hour calendar heatmap."""

from datetime import date, timedelta
from typing import Annotated

import plotly.graph_objects as go
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red.dli import NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR, get_model
from wp6_data.red.dli import data as dli_data
from wp6_data.red.lamp import (
    DAYLIGHT_THRESHOLD,
    LAMP_THRESHOLD,
    RECENT_DAYS,
    LampState,
    derive_lamp_model,
    lamp_state_grid,
)
from wp6_data.shared import render_date_filter, render_page, render_stat_grid, utc_day_bounds

router = APIRouter()

PAGE_TITLE = "SPoHF Red - Lamp Calendar"

# Lamps get a hue sunlight never takes, so "artificial" reads before the legend
# does. Night is the recessive state — most of a winter grid is night, and it is
# the least interesting thing on the page.
STATE_COLOURS = {
    LampState.DARK: "#eceff3",
    LampState.DAYLIGHT: "#fbbf24",
    LampState.DAYLIGHT_LIT: "#c026d3",
    LampState.LIT: "#7c3aed",
}
STATE_LABELS = {
    LampState.DARK: "Dark (no lamp)",
    LampState.DAYLIGHT: "Daylight",
    LampState.DAYLIGHT_LIT: "Daylight + lamps",
    LampState.LIT: "Lamps only",
}


def _discrete_colorscale() -> list:
    """A three-step scale, so a state is a block of colour rather than a gradient."""
    steps = []
    n = len(STATE_COLOURS)
    for i, colour in enumerate(STATE_COLOURS.values()):
        steps.append([i / n, colour])
        steps.append([(i + 1) / n, colour])
    return steps


def _make_calendar(grid, start: date, end: date) -> go.Figure:
    """Hours down, days across — the shape a grower already reads a schedule in."""
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    pivot = grid.pivot_table(index="hour", columns="date", values="state", aggfunc="max")
    pivot = pivot.reindex(index=range(24), columns=dates)

    canopy = grid.pivot_table(index="hour", columns="date", values="canopy_par", aggfunc="mean")
    canopy = canopy.reindex(index=range(24), columns=dates)

    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy().tolist(),
            x=[d.isoformat() for d in dates],
            y=[f"{h:02d}:00" for h in range(24)],
            customdata=canopy.to_numpy().tolist(),
            colorscale=_discrete_colorscale(),
            zmin=0.5,
            zmax=len(STATE_COLOURS) + 0.5,
            hoverongaps=False,
            xgap=0,
            ygap=0,
            colorbar={
                "tickvals": [int(s) for s in STATE_COLOURS],
                "ticktext": [STATE_LABELS[s] for s in STATE_COLOURS],
                "thickness": 14,
                "tickfont": {"size": 11},
                "outlinewidth": 0,
            },
            hovertemplate=(
                "%{x} %{y}<br>canopy PAR = %{customdata:.0f} µmol/m²/s<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        template="plotly_white",
        height=560,
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"title": "", "type": "category", "nticks": 20},
        yaxis={"title": "Hour (UTC)", "autorange": "reversed", "dtick": 2},
    )
    return fig


@router.get("/lamps", response_class=HTMLResponse)
async def dli_lamps(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Show which hours the lamps ran, read straight off the two PAR sensors."""
    if not dli_data.is_connected():
        return render_page(PAGE_TITLE, "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    model = get_model()

    today = date.today()
    if end is None:
        end = today
    if start is not None and start > end:
        start = end

    # The default is all of it. Rather than reach back to a fixed epoch — which
    # lands on years the sensors did not exist for — leave the query unbounded
    # and let the first reading decide where the calendar starts.
    _, end_dt = utc_day_bounds(end)
    start_dt = utc_day_bounds(start)[0] if start is not None else None

    try:
        par_df = await dli_data.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
    except Exception as e:
        return render_page(PAGE_TITLE, f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    if par_df.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Lamp Calendar</h1>{render_date_filter(start or end, end)}"
            "<p>No PAR readings in this range.</p>",
            show_back_link=True, back_url="/dli",
        )

    above_df = par_df[par_df["device"] == NATURAL_LIGHT_SENSOR]
    canopy_df = par_df[par_df["device"] == TOTAL_LIGHT_SENSOR]

    grid = lamp_state_grid(above_df, canopy_df)

    # The same model /dli/forecast runs on, so the two pages cannot disagree
    # about whether the lamps are running now. The grid classifies the past from
    # the readings alone and needs nothing from it.
    lamp = derive_lamp_model(
        above_df, canopy_df,
        attenuation=model.attenuation_factor if model.is_trained() else None,
    )

    if grid.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Lamp Calendar</h1>{render_date_filter(start or end, end)}"
            "<p>Both PAR sensors are needed to tell lamp light from daylight, "
            "and they do not overlap in this range.</p>",
            show_back_link=True, back_url="/dli",
        )

    # "All" means all of *this* page's data, on the filter as well as on load.
    data_start = min(grid["date"])
    if start is None:
        start = data_start
    filter_html = render_date_filter(start, end, all_start=data_start)

    lit = grid[grid["state"].isin([LampState.LIT, LampState.DAYLIGHT_LIT])]
    lit_days = lit["date"].nunique()
    observed_days = grid["date"].nunique()
    lamp_hours_per_lit_day = (len(lit) / lit_days) if lit_days else 0.0

    if lamp.is_lighting:
        schedule = ", ".join(f"{h:02d}" for h in sorted(lamp.hours_on))
        current = f"{schedule}h"
        current_sub = f"at {lamp.power_par:.0f} µmol/m²/s"
    else:
        current = "Off"
        current_sub = f"last {min(RECENT_DAYS, observed_days)} days"

    stats_html = render_stat_grid([
        (f"{lit_days}", "Days with lamps", f"of {observed_days} observed"),
        (f"{len(lit)}", "Lamp hours", "in this range"),
        (f"{lamp_hours_per_lit_day:.1f}", "Hours per lamp day", "average"),
        (current, "Current schedule", current_sub),
    ])

    chart_html = _make_calendar(grid, start, end).to_html(
        full_html=False, include_plotlyjs="cdn"
    )

    content = f"""
        <h1>Lamp Calendar</h1>
        <p>Every hour of every day, coloured by what the two PAR sensors say was
        lighting the crop.</p>
        {filter_html}
        {stats_html}
        {chart_html}
        <small>
            <strong>Lamps only</strong>: the canopy sensor ({TOTAL_LIGHT_SENSOR}) reads
            above {LAMP_THRESHOLD:.0f} µmol/m²/s while the above-lamp sensor
            ({NATURAL_LIGHT_SENSOR}) sees less than {DAYLIGHT_THRESHOLD:.0f} — light at
            the crop with no sun to explain it.<br/>
            <strong>Daylight + lamps</strong>: the sun is up, and the canopy is brighter
            than the roof sensor can account for by more than half the measured lamp
            level. Red runs its lamps through the short winter day, so this is most of
            the winter schedule.
            Gaps are hours with no usable reading, not hours that were dark — including
            whole days the sensors were switched off or out of the greenhouse, which
            report zeros rather than nothing.
        </small>
    """

    return render_page(PAGE_TITLE, content, show_back_link=True, back_url="/dli")
