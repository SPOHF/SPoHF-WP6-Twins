"""GET /broken-sensors — Sensor reliability assessment hub."""

from datetime import UTC, datetime
from typing import Annotated

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from plotly.subplots import make_subplots

from wp6_data.blue.treatments import (
    load_device_treatment_map,
    treatment_color,
)
from wp6_data.shared import render_hub_card, render_hub_grid, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter(dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "SPoHF Blue - Broken Sensors"

_YEAR_START = datetime(2025, 1, 1, tzinfo=UTC)
_YEAR_END = datetime(2026, 1, 1, tzinfo=UTC)

_SOIL_SENSORS: list[str] = [
    "soilMoisture", "soilTemperature", "soilConductivity", "soil_pH",
]
_WEATHER_TAG = "airTemperature"
_WEATHER_DEVICE = "weatherstation"

# Known issues per treatment from agronomic domain expertise
_MOISTURE_FLAGS: dict[str, str] = {
    "Ca":  "Consistently too low — sensor drift suspected",
    "K3":  "Consistently too low — sensor drift suspected",
}
_TEMP_FLAGS: dict[str, str] = {
    "Std": "Consistent positive offset vs. farm average",
}
_EC_FLAG = "Reads too low; frequent upward spikes"
_PH_FLAG = "Significant data gaps / downtime"

_EC_SPIKE_THRESHOLD = 800.0   # μS/cm — values above considered spike outliers
_AIR_TEMP_PEAK_C    = 40.0   # °C — unrealistic Netherlands outdoor temperature

_SENSOR_META: dict[str, tuple[str, str]] = {
    "soilMoisture":     ("Soil Moisture",    "%VWC"),
    "soilTemperature":  ("Soil Temperature", "°C"),
    "soilConductivity": ("EC",               "μS/cm"),
    "soil_pH":          ("pH",               ""),
    "airTemperature":   ("Air Temperature",  "°C"),
}

_SOIL_PANEL_ORDER: list[str] = [
    "soilMoisture", "soilTemperature", "soilConductivity", "soil_pH",
]


def _flag_badge(flagged: bool) -> str:
    if flagged:
        return '<span style="color:#dc2626;font-weight:600;">&#9888; Flagged</span>'
    return '<span style="color:#16a34a;">&#10003; OK</span>'


# ---------------------------------------------------------------------------
# Soil helpers
# ---------------------------------------------------------------------------

def _compute_soil_stats(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    treatment_map = load_device_treatment_map()
    df = df.copy()
    df["treatment"] = df["device"].map(treatment_map).fillna("Unknown")
    df["date"] = df["time"].dt.date

    result: dict[str, pd.DataFrame] = {}
    for tag in _SOIL_PANEL_ORDER:
        sdf = df[df["sensor"] == tag]
        if sdf.empty:
            result[tag] = pd.DataFrame()
            continue
        stats = (
            sdf.groupby("treatment")["value"]
            .agg(mean="mean", count="count")
            .reset_index()
        )
        if tag == "soilConductivity":
            spikes = (
                sdf[sdf["value"] > _EC_SPIKE_THRESHOLD]
                .groupby("treatment")["value"]
                .count()
                .rename("spikes")
                .reset_index()
            )
            stats = stats.merge(spikes, on="treatment", how="left")
            stats["spikes"] = stats["spikes"].fillna(0).astype(int)
        if tag == "soil_pH":
            day_counts = (
                sdf.groupby("treatment")["date"]
                .nunique()
                .rename("days")
                .reset_index()
            )
            stats = stats.merge(day_counts, on="treatment", how="left")
            stats["days"] = stats["days"].fillna(0).astype(int)
        result[tag] = stats
    return result


def _build_soil_chart(df: pd.DataFrame) -> str:
    treatment_map = load_device_treatment_map()
    df = df.copy()
    df["treatment"] = df["device"].map(treatment_map).fillna("Unknown")
    df["date"] = df["time"].dt.date

    daily = (
        df.groupby(["sensor", "treatment", "date"])["value"]
        .mean()
        .reset_index()
    )

    n = len(_SOIL_PANEL_ORDER)
    subplot_titles = [
        f"{_SENSOR_META[s][0]} ({_SENSOR_META[s][1]})" if _SENSOR_META[s][1]
        else _SENSOR_META[s][0]
        for s in _SOIL_PANEL_ORDER
    ]
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True,
        subplot_titles=subplot_titles,
        vertical_spacing=0.08,
    )

    seen: set[str] = set()
    for idx, sensor_tag in enumerate(_SOIL_PANEL_ORDER):
        row = idx + 1
        label, unit = _SENSOR_META[sensor_tag]
        y_label = f"{label} ({unit})" if unit else label
        sensor_data = daily[daily["sensor"] == sensor_tag]

        for treatment, tdf in sensor_data.groupby("treatment"):
            tdf = tdf.sort_values("date")
            color = treatment_color(str(treatment))
            show_legend = str(treatment) not in seen
            if show_legend:
                seen.add(str(treatment))
            fig.add_trace(
                go.Scatter(
                    x=tdf["date"].astype(str),
                    y=tdf["value"],
                    name=str(treatment),
                    mode="lines",
                    line={"color": color, "width": 1.5},
                    legendgroup=str(treatment),
                    showlegend=show_legend,
                    hovertemplate=(
                        f"<b>{treatment}</b><br>%{{x}}<br>"
                        f"{y_label}: %{{y:.2f}}<extra></extra>"
                    ),
                ),
                row=row, col=1,
            )
        fig.update_yaxes(title_text=y_label, row=row, col=1)

    fig.update_xaxes(showticklabels=True, tickformat="%b %Y", tickangle=-30)
    fig.update_layout(
        template="plotly_white",
        height=1100,
        hovermode="x unified",
        legend={"orientation": "v", "yanchor": "top", "y": 1,
                "xanchor": "left", "x": 1.02},
        margin={"r": 140},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def _render_soil_tables(stats: dict[str, pd.DataFrame]) -> str:
    sections: list[str] = []

    sdf = stats.get("soilMoisture", pd.DataFrame())
    if not sdf.empty:
        rows = []
        for _, r in sdf.sort_values("treatment").iterrows():
            t = str(r["treatment"])
            msg = _MOISTURE_FLAGS.get(t, "")
            rows.append(
                f"<tr><td>{t}</td><td>{r['mean']:.1f}</td>"
                f"<td>{int(r['count']):,}</td>"
                f"<td>{_flag_badge(bool(msg))}</td>"
                f"<td style='color:#6b7280;font-size:0.9em;'>{msg}</td></tr>"
            )
        sections.append(
            "<h3>Soil Moisture (%VWC)</h3>"
            "<table><thead><tr><th>Treatment</th><th>Mean (%VWC)</th>"
            "<th>Readings</th><th>Status</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    sdf = stats.get("soilTemperature", pd.DataFrame())
    if not sdf.empty:
        farm_mean = float(sdf["mean"].mean())
        rows = []
        for _, r in sdf.sort_values("treatment").iterrows():
            t = str(r["treatment"])
            offset = r["mean"] - farm_mean
            msg = _TEMP_FLAGS.get(t, "")
            rows.append(
                f"<tr><td>{t}</td><td>{r['mean']:.1f}</td>"
                f"<td>{offset:+.1f}</td>"
                f"<td>{int(r['count']):,}</td>"
                f"<td>{_flag_badge(bool(msg))}</td>"
                f"<td style='color:#6b7280;font-size:0.9em;'>{msg}</td></tr>"
            )
        sections.append(
            "<h3>Soil Temperature (°C)</h3>"
            "<table><thead><tr><th>Treatment</th><th>Mean (°C)</th>"
            "<th>Offset vs. avg (°C)</th><th>Readings</th><th>Status</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    sdf = stats.get("soilConductivity", pd.DataFrame())
    if not sdf.empty:
        rows = []
        for _, r in sdf.sort_values("treatment").iterrows():
            t = str(r["treatment"])
            spikes = int(r.get("spikes", 0))
            rows.append(
                f"<tr><td>{t}</td><td>{r['mean']:.1f}</td>"
                f"<td>{spikes:,}</td>"
                f"<td>{int(r['count']):,}</td>"
                f"<td>{_flag_badge(True)}</td>"
                f"<td style='color:#6b7280;font-size:0.9em;'>{_EC_FLAG}</td></tr>"
            )
        sections.append(
            "<h3>Soil EC (μS/cm)</h3>"
            f"<p style='color:#b45309;font-size:0.9em;'>All EC sensors flagged: {_EC_FLAG}. "
            f"Spike threshold: &gt;{_EC_SPIKE_THRESHOLD:.0f} μS/cm.</p>"
            "<table><thead><tr><th>Treatment</th><th>Mean (μS/cm)</th>"
            f"<th>Spikes (&gt;{_EC_SPIKE_THRESHOLD:.0f})</th>"
            "<th>Readings</th><th>Status</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    sdf = stats.get("soil_pH", pd.DataFrame())
    if not sdf.empty:
        rows = []
        for _, r in sdf.sort_values("treatment").iterrows():
            t = str(r["treatment"])
            days = int(r.get("days", 0))
            rows.append(
                f"<tr><td>{t}</td><td>{r['mean']:.2f}</td>"
                f"<td>{days}</td>"
                f"<td>{int(r['count']):,}</td>"
                f"<td>{_flag_badge(True)}</td>"
                f"<td style='color:#6b7280;font-size:0.9em;'>{_PH_FLAG}</td></tr>"
            )
        sections.append(
            "<h3>Soil pH</h3>"
            f"<p style='color:#b45309;font-size:0.9em;'>All pH sensors flagged: {_PH_FLAG}.</p>"
            "<table><thead><tr><th>Treatment</th><th>Mean pH</th>"
            "<th>Days with data</th><th>Readings</th><th>Status</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    return "\n".join(f"<article>{s}</article>" for s in sections)


# ---------------------------------------------------------------------------
# Weather helpers
# ---------------------------------------------------------------------------

def _build_weather_chart(df: pd.DataFrame) -> str:
    df = df.copy()
    df["date"] = df["time"].dt.date
    daily_max = df.groupby("date")["value"].max().reset_index().sort_values("date")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily_max["date"].astype(str),
            y=daily_max["value"],
            mode="lines",
            name="Daily max",
            line={"color": "#2563eb", "width": 1.5},
            hovertemplate="Date: %{x}<br>Max: %{y:.1f}°C<extra></extra>",
        )
    )
    fig.add_hline(
        y=_AIR_TEMP_PEAK_C,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text=f"Peak threshold ({_AIR_TEMP_PEAK_C:.0f}°C)",
        annotation_position="top right",
    )
    fig.update_layout(
        template="plotly_white",
        height=420,
        xaxis_title="Date",
        yaxis_title="Air Temperature (°C)",
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def _build_weather_table(df: pd.DataFrame) -> str:
    df = df.copy()
    df["month"] = df["time"].dt.to_period("M")

    monthly = df.groupby("month").agg(
        mean=("value", "mean"),
        max_val=("value", "max"),
    ).reset_index()
    peak_counts = (
        df[df["value"] > _AIR_TEMP_PEAK_C]
        .groupby("month")["value"]
        .count()
        .rename("peaks")
        .reset_index()
    )
    monthly = monthly.merge(peak_counts, on="month", how="left")
    monthly["peaks"] = monthly["peaks"].fillna(0).astype(int)
    monthly["month_str"] = monthly["month"].astype(str)

    rows = []
    for _, r in monthly.iterrows():
        rows.append(
            f"<tr><td>{r['month_str']}</td>"
            f"<td>{r['mean']:.1f}</td>"
            f"<td>{r['max_val']:.1f}</td>"
            f"<td>{int(r['peaks'])}</td>"
            f"<td>{_flag_badge(bool(r['peaks'] > 0))}</td></tr>"
        )

    if not rows:
        return "<p>No air temperature data for 2025.</p>"

    return (
        "<table><thead>"
        f"<tr><th>Month</th><th>Mean (°C)</th><th>Max (°C)</th>"
        f"<th>Peaks (&gt;{_AIR_TEMP_PEAK_C:.0f}°C)</th><th>Status</th></tr>"
        f"</thead><tbody>{''.join(rows)}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/broken-sensors", response_class=HTMLResponse)
async def broken_sensors_hub() -> str:
    content = f"""
        <h1>Unreliable Sensors</h1>
        <p>
          Reliability assessment for soil sensors and the weather station,
          based on 2025 data. Known issues are pre-labeled from agronomic
          domain expertise.
        </p>
        {render_hub_grid([
            render_hub_card(
                "Soil Sensors",
                "Moisture (Ca/K3 too low), temperature (Std offset), "
                "EC (all too low + spikes), and pH (all with data gaps) — "
                "2025 daily means and per-treatment reliability statistics.",
                href="/broken-sensors/soil",
                label="View Soil",
            ),
            render_hub_card(
                "Weather Station",
                "Air temperature from the field weather station. "
                "Spurious peaks above 40°C indicate a radiative heating "
                "artefact from direct solar radiation on the sensor housing.",
                href="/broken-sensors/weather",
                label="View Weather",
            ),
        ])}
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)


@router.get("/broken-sensors/soil", response_class=HTMLResponse)
async def broken_sensors_soil(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    try:
        df = await provider.fetch_data(
            sensor_tags=_SOIL_SENSORS,
            start=_YEAR_START,
            end=_YEAR_END,
        )
    except Exception as exc:
        return render_page(
            PAGE_TITLE,
            f"<h1>Soil Sensors</h1><p>Error fetching data: {exc}</p>",
            show_back_link=True, back_url="/broken-sensors",
        )

    if df.empty:
        return render_page(
            PAGE_TITLE,
            "<h1>Soil Sensors</h1><p>No soil sensor data for 2025.</p>",
            show_back_link=True, back_url="/broken-sensors",
        )

    stats = _compute_soil_stats(df)
    chart_html = _build_soil_chart(df)
    tables_html = _render_soil_tables(stats)

    content = f"""
        <h1>Soil Sensors &#8212; Reliability Assessment (2025)</h1>
        <p>
          Daily means per treatment aggregated over all 2025 readings.
          Pre-labeled known issues are highlighted in the tables below the chart.
        </p>
        <article>
          <details>
            <summary><strong>Known issues summary</strong></summary>
            <ul>
              <li><strong>Moisture:</strong> Ca and K3 &#8212;
                readings consistently too low (sensor drift suspected)</li>
              <li><strong>Temperature:</strong> Std &#8212;
                consistent positive offset vs. farm average</li>
              <li><strong>EC:</strong> All sensors &#8212;
                reads too low; frequent upward spikes</li>
              <li><strong>pH:</strong> All sensors &#8212;
                significant data gaps / downtime</li>
            </ul>
          </details>
        </article>
        <article>{chart_html}</article>
        {tables_html}
    """
    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/broken-sensors",
    )


@router.get("/broken-sensors/weather", response_class=HTMLResponse)
async def broken_sensors_weather(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    try:
        df = await provider.fetch_data(
            sensor_tags=[_WEATHER_TAG],
            device_names=[_WEATHER_DEVICE],
            start=_YEAR_START,
            end=_YEAR_END,
        )
    except Exception as exc:
        return render_page(
            PAGE_TITLE,
            f"<h1>Weather Station</h1><p>Error fetching data: {exc}</p>",
            show_back_link=True, back_url="/broken-sensors",
        )

    if df.empty:
        return render_page(
            PAGE_TITLE,
            "<h1>Weather Station</h1><p>No air temperature data for 2025.</p>",
            show_back_link=True, back_url="/broken-sensors",
        )

    total_peaks = int((df["value"] > _AIR_TEMP_PEAK_C).sum())
    chart_html = _build_weather_chart(df)
    table_html = _build_weather_table(df)

    content = f"""
        <h1>Weather Station &#8212; Air Temperature (2025)</h1>
        <p>
          The field weather station reports spurious air temperature peaks well
          above realistic values for the Netherlands. Readings above
          <strong>40&#176;C</strong> are artefacts caused by direct solar radiation
          on the unshielded sensor housing (radiative heating).
          Total flagged readings in 2025: <strong>{total_peaks:,}</strong>.
        </p>
        <article>{chart_html}</article>
        <article>
          <h3>Monthly Summary</h3>
          {table_html}
        </article>
    """
    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/broken-sensors",
    )
