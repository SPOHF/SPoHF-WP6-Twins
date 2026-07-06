"""GET /monitor/microclimate — Air temperature, humidity, and leaf sensors."""

from datetime import date
from typing import Annotated

import plotly.graph_objects as go
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from plotly.subplots import make_subplots

from wp6_data.blue.treatments import (
    load_device_treatment_map,
    treatment_color,
)
from wp6_data.shared import render_date_filter, render_page, resolve_date_range
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Microclimate"

MICROCLIMATE_SENSORS = [
    "airTemperature", "temperature", "humidity",
    "leaf_moisture", "leaf_temperature",
]

# Panels are ordered: in-canopy temp first, then outdoor reference,
# then humidity, leaf wetness, leaf temp.
# (sensor_tags_in_group, subplot_row, y-axis label)
_PANELS = [
    ({"temperature"},          1, "In-Canopy Temp (\u00b0C)"),
    ({"airTemperature"},       2, "Outdoor Air Temp (\u00b0C)"),
    ({"humidity"},             3, "In-Canopy Humidity (%RH)"),
    ({"leaf_moisture"},        4, "Leaf Wetness"),
    ({"leaf_temperature"},     5, "Leaf Temp (\u00b0C)"),
]


@router.get("/microclimate", response_class=HTMLResponse)
async def microclimate(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Microclimate dashboard: air temperature, humidity, and leaf sensors."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=MICROCLIMATE_SENSORS,
            start=start_dt,
            end=end_dt,
        )
    except Exception as e:
        return render_page(
            PAGE_TITLE, f"<p>Error fetching data: {e}</p>",
            show_back_link=True, back_url="/sensor-monitor",
            data_source=provider.data_source_label,
        )

    date_filter = render_date_filter(start, end)

    if df.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Microclimate</h1>{date_filter}"
            "<p>No microclimate sensor data for the selected period.</p>",
            show_back_link=True, back_url="/sensor-monitor",
            data_source=provider.data_source_label,
        )

    chart_html = _build_chart(df)

    content = f"""
        <h1>Microclimate</h1>
        {date_filter}
        {chart_html}
    """
    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/sensor-monitor",
        data_source=provider.data_source_label,
    )


def _build_chart(df) -> str:
    """Five-panel subplot: in-canopy temp, outdoor temp, humidity, leaf wetness, leaf temp.

    Each device line is coloured by its fertiliser treatment so that
    treatments are visually comparable across all panels.
    """
    treatment_map = load_device_treatment_map()
    df = df.copy()
    df["treatment"] = df["device"].map(treatment_map).fillna("Unknown")

    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True,
        vertical_spacing=0.07,
    )

    seen_treatments: set[str] = set()

    for sensor_tags, row, y_label in _PANELS:
        panel_df = df[df["sensor"].isin(sensor_tags)]
        if panel_df.empty:
            continue
        for (device, treatment), device_df in panel_df.groupby(["device", "treatment"]):
            device_df = device_df.sort_values("time")
            color = treatment_color(treatment)
            show = treatment not in seen_treatments
            if show:
                seen_treatments.add(treatment)
            fig.add_trace(
                go.Scatter(
                    x=device_df["time"],
                    y=device_df["value"],
                    name=treatment,
                    mode="lines",
                    line={"color": color, "width": 1.5},
                    legendgroup=treatment,
                    showlegend=show,
                    hovertemplate=(
                        f"<b>{device}</b> [{treatment}]<br>"
                        "%{x}<br>"
                        f"{y_label}: %{{y:.2f}}"
                        "<extra></extra>"
                    ),
                ),
                row=row, col=1,
            )
        fig.update_yaxes(title_text=y_label, row=row, col=1)

    fig.update_xaxes(showticklabels=True, tickformat="%d %b %Y", tickangle=-30)

    fig.update_layout(
        template="plotly_white",
        height=1200,
        hovermode="x unified",
        legend={"orientation": "v", "yanchor": "top", "y": 1,
                "xanchor": "left", "x": 1.02},
        margin={"r": 140},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")
