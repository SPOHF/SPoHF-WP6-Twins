"""GET /sensor-monitor/soil — Soil conditions with optional fertigation overlay."""

import csv
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
from wp6_data.config import Settings
from wp6_data.shared import render_date_filter, render_page, resolve_date_range
from wp6_data.shared.fertigation import resolve_fertigation_csv_path
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

_settings = Settings()


def _fertigation_csv_path():
    return resolve_fertigation_csv_path(_settings.blue_fertigation_events_csv)


def _load_fertigation_event_days() -> tuple[list[date], tuple[date, date] | None]:
    """Load global fertigation event dates from CSV (volume > 0 only)."""
    path = _fertigation_csv_path()
    if not path.exists():
        return [], None

    days: set[date] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                day_raw = (row.get("date") or "").strip()
                if not day_raw:
                    continue
                try:
                    day = date.fromisoformat(day_raw)
                except ValueError:
                    continue

                vol_raw = (row.get("volume_ml_per_plant") or "").strip()
                try:
                    volume = float(vol_raw)
                except ValueError:
                    volume = 0.0
                if volume <= 0:
                    continue
                days.add(day)
    except OSError:
        return [], None

    sorted_days = sorted(days)
    if not sorted_days:
        return [], None
    return sorted_days, (sorted_days[0], sorted_days[-1])


def _fertigation_toggle_html(
    *,
    start: date,
    end: date,
    enabled: bool,
    available: bool,
) -> str:
    checked = " checked" if enabled else ""
    disabled = " disabled" if not available else ""
    hint = (
        "Overlay global fertigation event starts on the soil chart."
        if available
        else "No fertigation events CSV detected."
    )
    return f"""
        <article class="date-filter" style="margin-top:0.4rem;">
            <form method="get" id="soil-fertigation-toggle">
                <input type="hidden" name="start" value="{start.isoformat()}">
                <input type="hidden" name="end" value="{end.isoformat()}">
                <label style="display:flex;align-items:center;gap:0.5rem;margin:0;">
                    <input type="checkbox" name="fert_events" value="1"{checked}{disabled}
                           onchange="document.getElementById('soil-fertigation-toggle').submit()">
                    Show fertigation events
                </label>
                <small>{hint}</small>
            </form>
        </article>
    """


def _warning_banner_html(message: str | None) -> str:
    if not message:
        return ""
    return f"<article class=\"warning\"><strong>Notice:</strong> {message}</article>"


@router.get("/soil", response_class=HTMLResponse)
async def soil_conditions(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
    fert_events: Annotated[bool, Query(description="Show fertigation overlays")] = False,
) -> str:
    """Soil conditions dashboard: temperature, moisture, pH, conductivity."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)
    fert_days, fert_span = _load_fertigation_event_days()
    in_view_days = [d for d in fert_days if start <= d <= end]
    show_fert = bool(fert_events and fert_days)

    try:
        df = await provider.fetch_data(
            sensor_tags=SOIL_SENSORS,
            start=start_dt,
            end=end_dt,
        )
    except Exception as e:
        return render_page(
            PAGE_TITLE, f"<p>Error fetching data: {e}</p>",
            show_back_link=True, back_url="/sensor-monitor",
            data_source=provider.data_source_label,
        )

    extra_params = {"fert_events": "1"} if show_fert else None
    date_filter = render_date_filter(start, end, extra_params=extra_params)
    fert_toggle = _fertigation_toggle_html(
        start=start,
        end=end,
        enabled=show_fert,
        available=bool(fert_days),
    )

    warning = None
    if fert_events and fert_days and not in_view_days and fert_span is not None:
        warning = (
            "No fertigation events for the current date range. "
            "Available fertigation dates: "
            f"{fert_span[0].isoformat()} to {fert_span[1].isoformat()}."
        )

    if df.empty:
        return render_page(
            PAGE_TITLE,
            f"<h1>Soil Conditions</h1>{date_filter}{fert_toggle}"
            "<p>No soil sensor data for the selected period.</p>",
            show_back_link=True, back_url="/sensor-monitor",
            data_source=provider.data_source_label,
        )

    chart_html = _build_chart(df, fertigation_days=in_view_days if show_fert else [])

    content = f"""
        <h1>Soil Conditions</h1>
        {date_filter}
        {fert_toggle}
        {_warning_banner_html(warning)}
        {chart_html}
    """
    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/sensor-monitor",
        data_source=provider.data_source_label,
    )


def _build_chart(df, *, fertigation_days: list[date]) -> str:
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

    # Farm-wide fertigation starts as vertical lines across all panels.
    for d in fertigation_days:
        fig.add_vline(
            x=d.isoformat(),
            line_width=1,
            line_dash="dot",
            line_color="rgba(14, 165, 233, 0.9)",
            row="all",
            col=1,
        )

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
