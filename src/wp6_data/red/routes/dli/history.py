"""GET /dli/history — DLI chart comparing natural light vs total light over time."""

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
    calculate_lamp_contribution,
)
from wp6_data.red.dli import data as dli_data
from wp6_data.shared import (
    render_date_filter,
    render_page,
    render_stat_grid,
    render_table,
    resolve_date_range,
)

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI History"


@router.get("/history", response_class=HTMLResponse)
async def dli_history(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """DLI chart comparing natural light vs total light over time."""
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

    # Rename devices to friendly labels
    device_labels = {
        NATURAL_LIGHT_SENSOR: "Natural Light",
        TOTAL_LIGHT_SENSOR: "Total Light",
    }
    dli_df["source"] = dli_df["device"].map(device_labels).fillna(dli_df["device"])

    # Pivot data for cleaner charts
    natural_data = dli_df[dli_df["device"] == NATURAL_LIGHT_SENSOR][
        ["date", "dli", "photoperiod_hours"]
    ].rename(columns={"dli": "natural_dli", "photoperiod_hours": "natural_hours"})
    total_data = dli_df[dli_df["device"] == TOTAL_LIGHT_SENSOR][
        ["date", "dli", "photoperiod_hours"]
    ].rename(columns={"dli": "total_dli", "photoperiod_hours": "total_hours"})

    chart_df = natural_data.merge(total_data, on="date", how="outer").sort_values("date")

    # Create DLI line chart with area fill
    fig_dli = go.Figure()
    fig_dli.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["total_dli"],
        name="Total Light", mode="lines+markers",
        line={"color": "#2ecc71", "width": 2},
        marker={"size": 6},
        fill="tozeroy", fillcolor="rgba(46, 204, 113, 0.2)",
    ))
    fig_dli.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["natural_dli"],
        name="Natural Light", mode="lines+markers",
        line={"color": "#3498db", "width": 2},
        marker={"size": 6},
        fill="tozeroy", fillcolor="rgba(52, 152, 219, 0.2)",
    ))

    # Add trendline for Total DLI
    total_valid = chart_df.dropna(subset=["total_dli"])
    if len(total_valid) >= 2:
        trendline_y, slope_per_day = calculate_dli_trendline(
            total_valid["date"].tolist(),
            total_valid["total_dli"].values,
        )
        trend_label = f"Trend ({slope_per_day:+.2f}/day)"
        fig_dli.add_trace(go.Scatter(
            x=total_valid["date"], y=trendline_y,
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
        x=chart_df["date"], y=chart_df["total_hours"],
        name="Total Hours", marker_color="#2ecc71",
    ))
    fig_hours.update_layout(
        title="Photoperiod (hours of light)",
        yaxis_title="Hours",
        xaxis_title="",
        height=300,
        hovermode="x unified",
        margin={"t": 60, "b": 40},
    )
    chart_hours_html = fig_hours.to_html(full_html=False, include_plotlyjs=False)

    # Summary stats
    days_count = len(chart_df)
    natural_avg = chart_df["natural_dli"].mean() if "natural_dli" in chart_df else 0
    total_avg = chart_df["total_dli"].mean() if "total_dli" in chart_df else 0
    hours_avg = chart_df["total_hours"].mean() if "total_hours" in chart_df else 0

    extra_css = """
        .chart-section { margin-bottom: 30px; }
        td, th { text-align: center; }
    """

    stats_html = render_stat_grid([
        (f"{total_avg:.1f}", "Avg Total DLI"),
        (f"{natural_avg:.1f}", "Avg Natural DLI"),
        (f"{hours_avg:.1f}h", "Avg Photoperiod"),
        (f"{days_count}", "Days"),
    ], cols=4)

    # Build data table
    table_df = chart_df.sort_values("date", ascending=False)
    table_rows = []
    for _, row in table_df.iterrows():
        natural_dli_val = f"{row['natural_dli']:.1f}" if pd.notna(row.get("natural_dli")) else "-"
        total_dli_val = f"{row['total_dli']:.1f}" if pd.notna(row.get("total_dli")) else "-"
        total_hrs = f"{row['total_hours']:.1f}" if pd.notna(row.get("total_hours")) else "-"

        # Calculate lamp contribution
        lamp_dli = calculate_lamp_contribution(
            row.get("total_dli") if pd.notna(row.get("total_dli")) else None,
            row.get("natural_dli") if pd.notna(row.get("natural_dli")) else None,
        )
        lamp_str = f"{lamp_dli:.1f}" if lamp_dli is not None else "-"

        table_rows.append(
            [f"{row['date']}", natural_dli_val, total_dli_val, lamp_str, total_hrs]
        )

    data_table = render_table(
        ["Date", "Natural DLI", "Total DLI", "Lamp DLI", "Photoperiod"],
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
    """

    return render_page(
        PAGE_TITLE,
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )
