"""GET /dli/history — DLI over time, above the lamps and down at plant level."""

from datetime import date
from typing import Annotated

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red.dli import (
    NATURAL_LIGHT_SENSOR,
    TOTAL_LIGHT_SENSOR,
    calculate_daily_dli,
    calculate_dli_trendline,
)
from wp6_data.red.dli import data as dli_data
from wp6_data.red.lamp import derive_daily_lamp_profile, subtract_lamp_from_sensor
from wp6_data.shared import (
    render_date_filter,
    render_page,
    render_stat_grid,
    render_table,
    resolve_date_range,
)

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI History"

# The two sensors are at different *heights*, not two views of one quantity, and
# the labels say so. Calling `NATURAL_LIGHT_SENSOR` "Total light" and
# `TOTAL_LIGHT_SENSOR` "Natural light" implied the second contained the first,
# which is false in both directions: the roof sensor hangs above the lamps and
# sees more sky, so on a bright lamp-free day it out-reads the canopy. Under the
# old labels that drew as total < natural — a contradiction the reader had no way
# to resolve.
ABOVE_LABEL = "Light above lamps"
PLANT_LABEL = "Light below lamps, at plant level"


@router.get("/history", response_class=HTMLResponse)
async def dli_history(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """DLI over time, compared between the above-lamp and plant-level sensors."""
    if not dli_data.is_connected():
        return render_page(PAGE_TITLE, "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        par_df = await dli_data.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
    except Exception as e:
        return render_page(PAGE_TITLE, f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    filter_html = render_date_filter(start, end)

    if par_df.empty:
        return render_page(
            PAGE_TITLE,
            filter_html + "<h1>No PAR data found</h1>",
            show_back_link=True, back_url="/dli",
        )

    # Calculate DLI per device per day
    dli_df = calculate_daily_dli(par_df)

    if dli_df.empty:
        return render_page(
            PAGE_TITLE,
            filter_html + "<h1>Insufficient data for DLI calculation</h1>",
            show_back_link=True, back_url="/dli",
        )

    # Pivot data for cleaner charts
    above_data = dli_df[dli_df["device"] == NATURAL_LIGHT_SENSOR][
        ["date", "dli", "photoperiod_hours"]
    ].rename(columns={"dli": "above_dli", "photoperiod_hours": "above_hours"})
    plant_data = dli_df[dli_df["device"] == TOTAL_LIGHT_SENSOR][
        ["date", "dli", "photoperiod_hours"]
    ].rename(columns={"dli": "plant_dli", "photoperiod_hours": "plant_hours"})

    chart_df = above_data.merge(plant_data, on="date", how="outer").sort_values("date")

    # Lamp DLI is *measured*, not taken as the gap between the two sensors: the
    # gap is dominated by attenuation, so it runs negative whenever the sun is
    # out. Instead the lamp-lit hours are detected and their measured power
    # subtracted from the plant-level trace; what that removes is the lamp.
    chart_df = chart_df.merge(
        _measured_lamp_dli(
            par_df[par_df["device"] == NATURAL_LIGHT_SENSOR],
            par_df[par_df["device"] == TOTAL_LIGHT_SENSOR],
            plant_data,
        ),
        on="date", how="left",
    )

    # Create DLI line chart with area fill
    fig_dli = go.Figure()
    fig_dli.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["plant_dli"],
        name=PLANT_LABEL, mode="lines+markers",
        line={"color": "#2ecc71", "width": 2},
        marker={"size": 6},
        fill="tozeroy", fillcolor="rgba(46, 204, 113, 0.2)",
    ))
    fig_dli.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["above_dli"],
        name=ABOVE_LABEL, mode="lines+markers",
        line={"color": "#3498db", "width": 2},
        marker={"size": 6},
        fill="tozeroy", fillcolor="rgba(52, 152, 219, 0.2)",
    ))

    # Add trendline for the plant-level DLI — the one the crop actually gets
    plant_valid = chart_df.dropna(subset=["plant_dli"])
    if len(plant_valid) >= 2:
        trendline_y, slope_per_day = calculate_dli_trendline(
            plant_valid["date"].tolist(),
            plant_valid["plant_dli"].values,
        )
        trend_label = f"Trend ({slope_per_day:+.2f}/day)"
        fig_dli.add_trace(go.Scatter(
            x=plant_valid["date"], y=trendline_y,
            name=trend_label, mode="lines",
            line={"color": "#e74c3c", "width": 2, "dash": "dash"},
        ))

    fig_dli.update_layout(
        title="Daily Light Integral (DLI)",
        yaxis_title="DLI (mol/m²/day)",
        xaxis_title="",
        height=400,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"t": 60, "b": 40},
    )
    chart_dli_html = fig_dli.to_html(full_html=False, include_plotlyjs="cdn")

    # Create photoperiod chart
    fig_hours = go.Figure()
    fig_hours.add_trace(go.Bar(
        x=chart_df["date"], y=chart_df["plant_hours"],
        name="Hours of light", marker_color="#2ecc71",
    ))
    fig_hours.update_layout(
        title="Photoperiod at plant level (hours of light)",
        yaxis_title="Hours",
        xaxis_title="",
        height=300,
        hovermode="x unified",
        margin={"t": 60, "b": 40},
    )
    chart_hours_html = fig_hours.to_html(full_html=False, include_plotlyjs=False)

    # Summary stats
    days_count = len(chart_df)
    above_avg = chart_df["above_dli"].mean() if "above_dli" in chart_df else 0
    plant_avg = chart_df["plant_dli"].mean() if "plant_dli" in chart_df else 0
    hours_avg = chart_df["plant_hours"].mean() if "plant_hours" in chart_df else 0

    extra_css = """
        .chart-section { margin-bottom: 30px; }
        td, th { text-align: center; }
    """

    stats_html = render_stat_grid([
        (f"{plant_avg:.1f}", "Avg DLI at plant level", "below lamps"),
        (f"{above_avg:.1f}", "Avg DLI above lamps", "roof sensor"),
        (f"{hours_avg:.1f}h", "Avg Photoperiod", "at plant level"),
        (f"{days_count}", "Days"),
    ], cols=4)

    # Build data table
    table_df = chart_df.sort_values("date", ascending=False)
    table_rows = []
    for _, row in table_df.iterrows():
        above_dli_val = f"{row['above_dli']:.1f}" if pd.notna(row.get("above_dli")) else "-"
        plant_dli_val = f"{row['plant_dli']:.1f}" if pd.notna(row.get("plant_dli")) else "-"
        plant_hrs = f"{row['plant_hours']:.1f}" if pd.notna(row.get("plant_hours")) else "-"
        lamp_str = f"{row['lamp_dli']:.1f}" if pd.notna(row.get("lamp_dli")) else "-"

        table_rows.append(
            [f"{row['date']}", above_dli_val, plant_dli_val, lamp_str, plant_hrs]
        )

    data_table = render_table(
        ["Date", "DLI above lamps", "DLI at plant level", "Lamp DLI", "Photoperiod"],
        table_rows,
        sortable=False,
    )
    table_html = f"""
        <details>
            <summary>View Data Table</summary>
            {data_table}
        </details>
    """

    content = f"""
        {filter_html}
        {stats_html}
        <div class="chart-section">{chart_dli_html}</div>
        <div class="chart-section">{chart_hours_html}</div>
        {table_html}
        <small>
            The two sensors sit at different heights, so this is not one light
            measured twice. <strong>{ABOVE_LABEL}</strong> ({NATURAL_LIGHT_SENSOR})
            hangs at the roof, above the lamps, and sees more of the sky;
            <strong>{PLANT_LABEL}</strong> ({TOTAL_LIGHT_SENSOR}) sits under the
            lamps and under everything between them. On a bright day with the lamps
            off the plant-level line therefore runs <em>below</em> the roof line —
            that is the greenhouse absorbing light, not a sensor fault. In winter,
            with the lamps on, it climbs back above it.<br/>
            <strong>Lamp DLI</strong> is measured from the hours the lamps were
            actually lit, never as the gap between the two lines: that gap is mostly
            structural loss, and reading it as lamp light would go negative every
            sunny day. Days without a usable lamp reading show "-", not zero.
        </small>
    """

    return render_page(
        PAGE_TITLE,
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )


def _measured_lamp_dli(
    above_df: pd.DataFrame,
    plant_df: pd.DataFrame,
    plant_data: pd.DataFrame,
) -> pd.DataFrame:
    """Per-day lamp DLI, measured by removing the lamp from the plant-level trace.

    Returns a ``date``/``lamp_dli`` frame carrying only the days the lamp profile
    could actually judge. A day the profile never saw is absent — and so reads as
    "-" rather than as zero lamp light, which would be a claim the data does not
    support.
    """
    empty = pd.DataFrame({"date": [], "lamp_dli": []})
    if above_df.empty or plant_df.empty:
        return empty

    profile = derive_daily_lamp_profile(above_df, plant_df)
    if profile.empty:
        return empty

    lamp_free_dli = calculate_daily_dli(subtract_lamp_from_sensor(plant_df, profile))
    if lamp_free_dli.empty:
        return empty

    merged = plant_data.merge(
        lamp_free_dli[["date", "dli"]].rename(columns={"dli": "lamp_free_dli"}),
        on="date", how="inner",
    )
    merged = merged[merged["date"].isin(set(profile["date"]))]
    merged["lamp_dli"] = merged["plant_dli"] - merged["lamp_free_dli"]

    return merged[["date", "lamp_dli"]]
