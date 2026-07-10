"""GET /monitor/light — PAR and solar radiation chart."""

from datetime import date
from typing import Annotated

import plotly.graph_objects as go
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from plotly.subplots import make_subplots

from wp6_data.shared import render_date_filter, render_page, resolve_date_range
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Light"

LIGHT_SENSORS = ["par", "solarRadiation"]

# (sensor_tag, subplot_row, y-axis label)
_PANELS = [
    ("par",             1, "PAR (\u03bcmol/m\u00b2/s)"),
    ("solarRadiation",  2, "Solar Radiation (W/m\u00b2)"),
]


@router.get("/light", response_class=HTMLResponse)
async def light_chart(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Light dashboard: PAR and solar radiation."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=LIGHT_SENSORS,
            start=start_dt,
            end=end_dt,
        )
    except Exception as e:
        return render_page(
            PAGE_TITLE, f"<p>Error fetching data: {e}</p>",
            show_back_link=True, back_url="/sensor-monitor",
        )

    date_filter = render_date_filter(start, end)

    if df.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Light</h1>{date_filter}"
            "<p>No light sensor data for the selected period.</p>",
            show_back_link=True, back_url="/sensor-monitor",
        )

    chart_html = _build_chart(df)

    content = f"""
        <h1>Light</h1>
        {date_filter}
        {chart_html}
    """
    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/sensor-monitor",
    )


def _build_chart(df) -> str:
    """Single panel: PAR sensors on the left y-axis, solar radiation on the right."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # PAR — one line per device, each a distinct colour, left y-axis
    par_df = df[df["sensor"] == "par"]
    _PAR_COLORS = [
        "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4",
        "#10b981", "#f97316", "#6366f1",
    ]
    for i, (device, device_df) in enumerate(par_df.groupby("device")):
        device_df = device_df.sort_values("time")
        color = _PAR_COLORS[i % len(_PAR_COLORS)]
        fig.add_trace(
            go.Scatter(
                x=device_df["time"],
                y=device_df["value"],
                name=device,
                mode="lines",
                line={"color": color, "width": 1.5},
                legendgroup=device,
                hovertemplate=(
                    f"<b>{device}</b><br>"
                    "%{x}<br>"
                    "PAR: %{y:.1f} \u03bcmol/m\u00b2/s"
                    "<extra></extra>"
                ),
            ),
            secondary_y=False,
        )

    # Solar radiation — weather station reference, right y-axis
    sol_df = df[df["sensor"] == "solarRadiation"]
    for device, device_df in sol_df.groupby("device"):
        device_df = device_df.sort_values("time")
        fig.add_trace(
            go.Scatter(
                x=device_df["time"],
                y=device_df["value"],
                name=f"{device} (solar)",
                mode="lines",
                line={"color": "#111827", "width": 1.5, "dash": "dot"},
                legendgroup=device,
                hovertemplate=(
                    f"<b>{device}</b><br>"
                    "%{x}<br>"
                    "Solar: %{y:.1f} W/m\u00b2"
                    "<extra></extra>"
                ),
            ),
            secondary_y=True,
        )

    fig.update_yaxes(title_text="PAR (\u03bcmol/m\u00b2/s)", secondary_y=False)
    fig.update_yaxes(title_text="Solar Radiation (W/m\u00b2)", secondary_y=True)

    fig.update_layout(
        template="plotly_white",
        height=450,
        hovermode="x unified",
        legend={"orientation": "v", "yanchor": "top", "y": 1,
                "xanchor": "left", "x": 1.08},
        margin={"r": 200},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")
