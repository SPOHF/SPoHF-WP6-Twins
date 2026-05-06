"""GET /monitor/soil — Soil conditions: temperature, moisture, pH, conductivity."""

from datetime import date
from typing import Annotated

import plotly.graph_objects as go
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from plotly.subplots import make_subplots

from wp6_data.blue.routes.monitor._treatment import (
    load_device_treatment_map,
    treatment_color,
)
from wp6_data.shared import render_date_filter, render_page, resolve_date_range
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Soil Conditions"

SOIL_SENSORS = ["soilTemperature", "soilMoisture", "soil_pH", "soilConductivity"]

# (sensor_tag, subplot_row, y-axis label)
_PANELS = [
    ("soilTemperature", 1, "Soil Temp (°C)"),
    ("soilMoisture",    2, "Moisture (%VWC)"),
    ("soil_pH",         3, "pH"),
    ("soilConductivity",4, "EC (μS/cm)"),
]


@router.get("/soil", response_class=HTMLResponse)
async def soil_conditions(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Soil conditions dashboard: temperature, moisture, pH, conductivity."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=SOIL_SENSORS,
            start=start_dt,
            end=end_dt,
        )
    except Exception as e:
        return render_page(
            PAGE_TITLE, f"<p>Error fetching data: {e}</p>",
            show_back_link=True, back_url="/monitor",
            data_source=provider.data_source_label,
        )

    date_filter = render_date_filter(start, end)

    if df.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Soil Conditions</h1>{date_filter}"
            "<p>No soil sensor data for the selected period.</p>",
            show_back_link=True, back_url="/monitor",
            data_source=provider.data_source_label,
        )

    chart_html = _build_chart(df)

    content = f"""
        <h1>Soil Conditions</h1>
        {date_filter}
        {chart_html}
    """
    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/monitor",
        data_source=provider.data_source_label,
    )


def _build_chart(df) -> str:
    """Four-panel subplot: one row per soil sensor type.

    Readings are aggregated to hourly means per fertiliser treatment so
    treatments are directly comparable on the same axis.
    """
    treatment_map = load_device_treatment_map()
    df = df.copy()
    df["treatment"] = df["device"].map(treatment_map).fillna("Unknown")

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        vertical_spacing=0.09,
    )

    seen_treatments: set[str] = set()

    for sensor_tag, row, y_label in _PANELS:
        sensor_df = df[df["sensor"] == sensor_tag]
        if sensor_df.empty:
            continue

        # Aggregate all devices sharing a treatment into an hourly mean
        hourly = (
            sensor_df
            .set_index("time")
            .groupby("treatment")["value"]
            .resample("1h")
            .mean()
            .dropna()
            .reset_index()
        )

        for treatment, tdf in hourly.groupby("treatment"):
            tdf = tdf.sort_values("time")
            color = treatment_color(treatment)
            show = treatment not in seen_treatments
            if show:
                seen_treatments.add(treatment)
            fig.add_trace(
                go.Scatter(
                    x=tdf["time"],
                    y=tdf["value"],
                    name=treatment,
                    mode="lines",
                    line={"color": color, "width": 2},
                    legendgroup=treatment,
                    showlegend=show,
                    hovertemplate=(
                        f"<b>{treatment}</b><br>"
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
        height=1000,
        hovermode="x unified",
        legend={"orientation": "v", "yanchor": "top", "y": 1,
                "xanchor": "left", "x": 1.02},
        margin={"r": 140},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")
