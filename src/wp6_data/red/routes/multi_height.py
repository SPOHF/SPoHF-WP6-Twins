import html
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_card, render_hub_card, render_hub_grid, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

from .. import deps
from ..db import (
    WIRE_SENSOR_HEIGHTS,
    WIRE_SENSOR_MEASUREMENTS,
    wire_device_id,
    wire_physical_id,
)
from ..utils import (
    PAR_COLORSCALE,
    svg_rect_to_plotly_rect,
    svg_to_data_uri,
    value_to_color,
)

SVG_BACKGROUND_PATH = Path(__file__).parent.parent / "static/greenhouse.svg"
SVG_LAYOUT_PATH = Path(__file__).parent.parent / "static/multi_height.svg"
USE_LATEST_DATE_IN_DATA = False

router = APIRouter(dependencies=[Depends(verify_session_user)])

# Views available under the Multi Height section. Each entry becomes a hub card
# on the landing page below. Add more here as additional height views are built.
MULTI_HEIGHT_VIEWS = [
    {
        "href": "/multi_height/single-simple",
        "title": "Simple Greenhouse View",
        "label": "Open view",
        "description": "Latest PAR and Daily Light Integral mapped onto the "
        "greenhouse layout at each sensor height.",
    },
    {
        "href": "/multi_height/wire-trends",
        "title": "Wire Sensor Trends",
        "label": "Open view",
        "description": "PAR, temperature, humidity and CO₂ over time from the "
        "multi-height wire — one line per height.",
    },
]


@router.get("/multi_height", response_class=HTMLResponse)
async def multi_height_landing(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
):
    """Landing page for the Multi Height section — a hub of height-based views."""
    cards = render_hub_grid([
        render_hub_card(
            view["title"], view["description"],
            href=view["href"], label=view["label"],
        )
        for view in MULTI_HEIGHT_VIEWS
    ])

    content = f"""
    <a href="/" class="back-link">← Home</a>
    <h1>Multi Height</h1>
    <p>Sensor data viewed across multiple heights in the greenhouse.</p>

    {cards}
    """

    return render_page(
        config.title,
        content,
        data_source=provider.data_source_label,
    )


def wire_ids() -> list[str]:
    """Physical wire ids declared in metadata (devices typed 'wire'), sorted."""
    ids = {
        wire_physical_id(device_id)
        for device_id, meta in deps.metadata.devices.items()
        if meta.type == "wire"
    }
    return sorted(ids)


def _pill_row(base_path, param, choices, active, preserve, label):
    """A labelled segmented toggle that swaps ``param`` (preserving other params).

    Reuses the shared ``.group-toggle`` / ``.group-btn`` styling from the chart
    page; each segment is a navigation link. ``choices`` is a list of
    ``(value, text)``; ``preserve`` a dict of other query params (falsy dropped);
    ``label`` is the row caption (e.g. "Device").
    """
    qs = "".join(f"&amp;{key}={val}" for key, val in preserve.items() if val)
    segments = []
    for value, text in choices:
        cls = "group-btn active" if value == active else "group-btn"
        segments.append(
            f'<a class="{cls}" style="text-decoration:none;" '
            f'href="{base_path}?{param}={value}{qs}">{text}</a>'
        )
    return (
        '<div style="display:flex;align-items:center;gap:0.75rem;'
        'margin-bottom:0.5rem;flex-wrap:wrap;">'
        f'<span style="font-weight:600;min-width:6rem;">{label}:</span>'
        '<div class="group-toggle" style="width:fit-content;">'
        + "".join(segments)
        + "</div></div>"
    )


@router.get("/multi_height/single-simple", response_class=HTMLResponse)
async def single_simple_page(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    day: Annotated[
        date | None,
        Query(alias="date", description="Day to view (YYYY-MM-DD); defaults to today"),
    ] = None,
    measurement: Annotated[
        str,
        Query(description="Measurement to map (par/temp/hum/co2); defaults to par"),
    ] = "par",
    wire: Annotated[
        str | None,
        Query(description="Which wire to show; defaults to the first declared"),
    ] = None,
    ):
    if measurement not in WIRE_SENSOR_MEASUREMENTS:
        measurement = "par"

    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    timezone = deps.base_settings.display_timezone
    is_par = measurement == "par"

    meta = deps.metadata.sensor_default(measurement)
    label = meta.alias or measurement
    value_label = f"{label} ({meta.unit})" if meta.unit else label

    df = await load_wire_readings()
    wire_devices = [wire_device_id(wire, h) for h in WIRE_SENSOR_HEIGHTS]

    # Default to the latest day this wire+measurement actually reported, not
    # "today" — the wire feed can lag, which would otherwise show empty boxes.
    if day is not None:
        target_date = day
    else:
        scoped = (
            df[df["device"].isin(wire_devices) & (df["measurement"] == measurement)]
            if not df.empty else df
        )
        target_date = (
            scoped["time"].dt.tz_convert(timezone).max().date()
            if not scoped.empty else None
        )

    df_today, target_day = filter_for_day(df, timezone, target_date=target_date)
    metrics = compute_sensor_metrics(df_today, measurement, wire)

    canvas_w, canvas_h, sensor_boxes, sensor_bands = parse_svg(SVG_LAYOUT_PATH)

    fig = make_mh_greenhouse_plot(
        metrics,
        canvas_w,
        canvas_h,
        sensor_boxes,
        sensor_bands,
        target_day,
        value_label=value_label,
        show_bands=is_par,
    )

    plot_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={
            "responsive": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": [
                "select2d",
                "lasso2d",
            ],
        },
    )

    plot_container = f"""
    <iframe
        srcdoc="{html.escape(plot_html, quote=True)}"
        style="
            width: 100%;
            height: 820px;
            border: 0;
            background: white;
            border-radius: 12px;
        "
    ></iframe>
    """

    # Chart below: cumulative DLI for PAR; raw value-over-time otherwise.
    # Scope to the selected wire so heights don't merge across wires.
    df_wire = df_today[df_today["device"].isin(wire_devices)] if not df_today.empty else df_today
    if is_par:
        chart_fig = make_cumulative_dli_plot(
            df_wire[df_wire["measurement"] == "par"], timezone, target_day, wire,
        )
        chart_title = "Cumulative DLI by height"
        chart_desc = (
            "Daily Light Integral accumulated through the day for each "
            "sensor height — the running total of the bands above."
        )
    else:
        chart_fig = make_wire_measurement_plot(df_wire, measurement, timezone)
        chart_title = f"{label} by height"
        chart_desc = f"{label} through the day for each sensor height."

    chart_html = chart_fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={"responsive": True, "displaylogo": False},
    )

    box_desc = f"Latest {label} values are shown inside the sensor boxes."
    if is_par:
        box_desc += " Daily Light Integral (DLI) is shown as horizontal bands."

    base = "/multi_height/single-simple"
    date_str = day.isoformat() if day else None
    wire_pills = _pill_row(
        base, "wire", [(w, w) for w in wires], wire,
        {"measurement": measurement, "date": date_str},
        label="Device",
    )
    measurement_pills = _pill_row(
        base, "measurement",
        [(m, deps.metadata.sensor_default(m).alias or m) for m in WIRE_SENSOR_MEASUREMENTS],
        measurement,
        {"wire": wire, "date": date_str},
        label="Measurement",
    )

    content = f"""
    <a href="/multi_height" class="back-link">← Multi Height</a>
    <h1>Simple Greenhouse View</h1>

    <div style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center;">
        {wire_pills}
        {measurement_pills}
    </div>

    {render_card(
        " ",
        plot_container,
        description=box_desc,
        card_class="card",
    )}

    {render_card(
        chart_title,
        chart_html,
        description=chart_desc,
        card_class="card",
    )}
    """

    return render_page(
        config.title,
        content,
        data_source=provider.data_source_label,
    )

### Wire Sensor Trends ###
# One trace colour per height, shared across all four charts so a given height
# reads as the same colour everywhere. Five colours for the five heights.
WIRE_HEIGHT_COLORS = ["#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#10b981"]

# Display name + unit per measurement type, keyed by the db measurement key.
WIRE_MEASUREMENT_LABELS = {
    "par": ("PAR", "µmol/m²/s"),
    "temp": ("Temperature", "°C"),
    "hum": ("Humidity", "%RH"),
    "co2": ("CO₂", "ppm"),
}


async def load_wire_sensor_data(start, end):
    """Tidy long wire-sensor readings for a UTC window: time, height, measurement, value."""
    df = await deps.db.get_wire_sensor_readings(start=start, end=end)

    if df.empty:
        return df

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["time", "value"])


def make_wire_measurement_plot(df, measurement, timezone):
    """Line chart for one measurement type, one line per height."""
    label, unit = WIRE_MEASUREMENT_LABELS[measurement]
    data = df[df["measurement"] == measurement] if not df.empty else df

    fig = go.Figure()

    for height in WIRE_SENSOR_HEIGHTS:
        d = data[data["height"] == height].sort_values("time") if not data.empty else data

        if d.empty:
            continue

        color = WIRE_HEIGHT_COLORS[(height - 1) % len(WIRE_HEIGHT_COLORS)]

        fig.add_trace(
            go.Scatter(
                # Convert UTC → local wall-clock so the axis matches the picker
                x=d["time"].dt.tz_convert(timezone).dt.tz_localize(None),
                y=d["value"],
                name=f"Height {height}",
                mode="lines",
                connectgaps=False,
                line=dict(color=color, width=2),
                hovertemplate=(
                    f"<b>Height {height}</b><br>%{{x|%Y-%m-%d %H:%M}}<br>"
                    f"{label}: %{{y:.2f}} {unit}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        height=360,
        hovermode="x unified",
        xaxis_title="Time",
        yaxis_title=f"{label} ({unit})",
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def _wire_range_form(start_day: date, end_day: date, wire: str) -> str:
    """A small From/To date-range form that GETs back to this view (keeps wire)."""
    return f"""
    <form method="get" style="display:flex;gap:12px;align-items:flex-end;
        margin-bottom:16px;flex-wrap:wrap;">
        <input type="hidden" name="wire" value="{wire}">
        <label>From<br>
            <input type="date" name="start" value="{start_day.isoformat()}">
        </label>
        <label>To<br>
            <input type="date" name="end" value="{end_day.isoformat()}">
        </label>
        <button type="submit">Update</button>
    </form>
    """


@router.get("/multi_height/wire-trends", response_class=HTMLResponse)
async def wire_trends_page(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[
        date | None, Query(description="Range start (YYYY-MM-DD); defaults to 7 days ago")
    ] = None,
    end: Annotated[
        date | None, Query(description="Range end (YYYY-MM-DD); defaults to today")
    ] = None,
    wire: Annotated[
        str | None, Query(description="Which wire to show; defaults to the first declared")
    ] = None,
):
    timezone = deps.base_settings.display_timezone

    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    end_day = end or date.today()
    start_day = start or (end_day - timedelta(days=7))

    # Translate the local day range to UTC bounds: start of start_day .. end of end_day
    start_utc = pd.Timestamp(start_day, tz=timezone).tz_convert("UTC").to_pydatetime()
    end_utc = (
        (pd.Timestamp(end_day, tz=timezone) + pd.Timedelta(days=1))
        .tz_convert("UTC")
        .to_pydatetime()
    )

    df = await load_wire_sensor_data(start_utc, end_utc)
    # Scope to the selected wire so heights don't merge across wires.
    wire_devices = [wire_device_id(wire, h) for h in WIRE_SENSOR_HEIGHTS]
    df = df[df["device"].isin(wire_devices)] if not df.empty else df

    charts_html = ""
    for i, measurement in enumerate(WIRE_SENSOR_MEASUREMENTS):
        fig = make_wire_measurement_plot(df, measurement, timezone)
        # Load plotly.js once (first chart), reference it for the rest
        chart_html = fig.to_html(
            include_plotlyjs="cdn" if i == 0 else False,
            full_html=False,
            config={"responsive": True, "displaylogo": False},
        )
        label, unit = WIRE_MEASUREMENT_LABELS[measurement]
        charts_html += render_card(f"{label} ({unit})", chart_html, card_class="card")

    wire_pills = _pill_row(
        "/multi_height/wire-trends", "wire", [(w, w) for w in wires], wire,
        {"start": start_day.isoformat(), "end": end_day.isoformat()},
        label="Device",
    )

    content = f"""
    <a href="/multi_height" class="back-link">← Multi Height</a>
    <h1>Wire Sensor Trends</h1>
    <p>Each measurement type over time, with one line per height on the
    selected multi-height wire.</p>

    {wire_pills}
    {_wire_range_form(start_day, end_day, wire)}
    {charts_html}
    """

    return render_page(
        config.title,
        content,
        data_source=provider.data_source_label,
    )


### Parse SVG ###
def parse_viewbox(svg_path: Path):
    root = ET.parse(svg_path).getroot()
    viewbox = root.attrib.get("viewBox")

    if viewbox:
        x, y, w, h = map(float, viewbox.split())
        return x, y, w, h

    width = float(re.sub(r"[^0-9.]", "", root.attrib["width"]))
    height = float(re.sub(r"[^0-9.]", "", root.attrib["height"]))
    return 0.0, 0.0, width, height


def parse_svg_rects(svg_path: Path):
    ns = {"svg": "http://www.w3.org/2000/svg"}
    root = ET.parse(svg_path).getroot()

    rects = {}

    for rect in root.findall(".//svg:rect", ns):
        rect_id = rect.attrib.get("id")
        if not rect_id:
            continue

        rects[rect_id] = {
            "x": float(rect.attrib.get("x", 0)),
            "y": float(rect.attrib.get("y", 0)),
            "width": float(rect.attrib.get("width", 0)),
            "height": float(rect.attrib.get("height", 0)),
            "rx": rect.attrib.get("rx"),
        }

    return rects

def parse_svg(svg_path: Path):
    _, _, canvas_w, canvas_h = parse_viewbox(svg_path)
    rects = parse_svg_rects(svg_path)

    sensor_boxes = {
        k: v for k, v in rects.items()
        if k.startswith("height_") and not k.endswith("_bg")
    }

    sensor_bands = {
        k.replace("_bg", ""): v for k, v in rects.items()
        if k.startswith("height_") and k.endswith("_bg")
    }

    return canvas_w, canvas_h, sensor_boxes, sensor_bands


### Load data ###
async def load_wire_readings():
    # All measurements per height from the wire (devices WS_01_01-h1..h5); the
    # retired s2100-10..15 sensors are gone (ADR 0001). Keeps the height and
    # measurement columns so the view can pivot per selected measurement.
    df = await deps.db.get_wire_sensor_readings()

    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df.dropna(subset=["time", "device", "value"])


### Filter to a single day ###
def filter_for_day(
    df, timezone, target_date=None, use_latest_date_in_data=USE_LATEST_DATE_IN_DATA,
):
    """Return the readings for one local day plus that day's start timestamp.

    ``target_date`` (a ``datetime.date``) pins an explicit day — used by the
    ``?date=`` URL param. When it's ``None`` the day defaults to today (or the
    latest day present in the data when ``use_latest_date_in_data`` is set).
    """
    df_local = df.copy()
    df_local["time_local"] = df_local["time"].dt.tz_convert(timezone)

    if target_date is not None:
        target_day = pd.Timestamp(target_date, tz=timezone).normalize()
    elif use_latest_date_in_data:
        target_day = df_local["time_local"].max().normalize()
    else:
        target_day = pd.Timestamp.now(tz=timezone).normalize()

    next_day = target_day + pd.Timedelta(days=1)

    mask = (
        (df_local["time_local"] >= target_day) &
        (df_local["time_local"] < next_day)
    )

    return df_local.loc[mask].drop(columns=["time_local"]), target_day


### DLI ###
def _dli_increments(sensor_df):
    """Per-reading DLI contributions (mol/m²) via trapezoidal integration.

    Returns the frame sorted by time with a ``dli_increment`` column — each
    interval's PAR (averaged across its endpoints) times its duration. Gaps are
    clipped to 15 min so a missing stretch can't inflate the integral. The total
    DLI is the sum; the running ``cumsum`` is the DLI accrued up to each time.
    Returns ``None`` when there are too few readings to integrate.
    """
    d = sensor_df.sort_values("time").copy()

    if len(d) < 2:
        return None

    d["next_time"] = d["time"].shift(-1)
    d["next_value"] = d["value"].shift(-1)

    d["dt_seconds"] = (d["next_time"] - d["time"]).dt.total_seconds()
    d["dt_seconds"] = d["dt_seconds"].clip(lower=0, upper=900)

    d["avg_value"] = (d["value"] + d["next_value"]) / 2
    d = d.dropna(subset=["dt_seconds", "avg_value"])

    d["dli_increment"] = (d["avg_value"] * d["dt_seconds"]) / 1_000_000
    return d


def compute_dli(sensor_df):
    """Total DLI (mol/m²) for a single sensor's readings over the day."""
    d = _dli_increments(sensor_df)

    if d is None:
        return None

    return float(d["dli_increment"].sum())


def compute_cumulative_dli(sensor_df):
    """Running DLI (mol/m²) for one sensor: time + cumulative_dli columns.

    The DLI accrued from the start of the data up to each timestamp — i.e. the
    integral of :func:`compute_dli` traced over the day. ``None`` when there are
    too few readings.
    """
    d = _dli_increments(sensor_df)

    if d is None:
        return None

    d["cumulative_dli"] = d["dli_increment"].cumsum()
    return d[["time", "cumulative_dli"]]


### Metrics ###
def compute_sensor_metrics(df_day, measurement, wire):
    """Latest value per height for ``wire``/``measurement`` (+ daily DLI, PAR only).

    ``sensor_id`` is the SVG box id (``height_N``); the wire device it reads is
    derived from the selected wire and height.
    """
    rows = []
    data = df_day[df_day["measurement"] == measurement] if not df_day.empty else df_day

    for height in WIRE_SENSOR_HEIGHTS:
        box_id = f"height_{height}"
        device = wire_device_id(wire, height)
        d = (
            data[data["device"] == device].sort_values("time")
            if not data.empty else data
        )

        if d.empty:
            rows.append({
                "sensor_id": box_id,
                "latest_value": None,
                "dli_today": None,
            })
            continue

        latest = d.iloc[-1]

        rows.append({
            "sensor_id": box_id,
            "latest_value": float(latest["value"]),
            # DLI is a PAR-only aggregate; left empty for other measurements.
            "dli_today": compute_dli(d) if measurement == "par" else None,
        })

    return pd.DataFrame(rows)


### Plot ###
def _format_reading(value: float) -> str:
    """Box label: whole numbers for large readings, one decimal for small."""
    return f"{value:.0f}" if abs(value) >= 100 else f"{value:.1f}"


def make_mh_greenhouse_plot(
    metrics,
    canvas_w,
    canvas_h,
    sensor_boxes,
    sensor_bands,
    target_day,
    value_label="PAR",
    show_bands=True,
):
    fig = go.Figure()

    # fix background
    fig.add_shape(
        type="rect",
        x0=0,
        x1=canvas_w,
        y0=0,
        y1=canvas_h,
        fillcolor="#ffffff",
        line=dict(width=0),
        layer="below",
    )

    latest_vals = metrics["latest_value"].dropna()
    dli_vals = metrics["dli_today"].dropna()

    latest_min = float(latest_vals.min()) if not latest_vals.empty else 0.0
    latest_max = float(latest_vals.max()) if not latest_vals.empty else 1.0

    dli_min = float(dli_vals.min()) if not dli_vals.empty else 0.0
    dli_max = float(dli_vals.max()) if not dli_vals.empty else 1.0

    # background
    fig.add_layout_image(
        dict(
            source=svg_to_data_uri(SVG_BACKGROUND_PATH),
            xref="x",
            yref="y",
            x=0,
            y=canvas_h,
            sizex=canvas_w,
            sizey=canvas_h,
            sizing="stretch", #bg fix
            layer="below",
        )
    )

    for _, row in metrics.iterrows():
        sid = row["sensor_id"]

        # --- bands (DLI shading; PAR only) ---
        if show_bands and sid in sensor_bands:
            x0, x1, y0, y1 = svg_rect_to_plotly_rect(sensor_bands[sid], canvas_h)

            fig.add_shape(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=value_to_color(row["dli_today"], dli_min, dli_max, alpha=0.4),
                line=dict(width=0),
                layer="below",
            )

        # --- sensor box ---
        if sid in sensor_boxes:
            x0, x1, y0, y1 = svg_rect_to_plotly_rect(sensor_boxes[sid], canvas_h)

            fig.add_shape(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=value_to_color(
                    row["latest_value"], latest_min, latest_max, alpha=0.9,
                ),
                line=dict(color="#111111", width=1.5),
            )

            label = (
                "—" if pd.isna(row["latest_value"])
                else _format_reading(row["latest_value"])
            )

            fig.add_annotation(
                x=(x0 + x1) / 2,
                y=(y0 + y1) / 2,
                text=label,
                showarrow=False,
                font=dict(size=11, color="#111111"),
                xanchor="center",
                yanchor="middle",
            )

    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(
                color=[latest_min, latest_max],
                colorscale=PAR_COLORSCALE,
                cmin=latest_min,
                cmax=latest_max,
                showscale=True,
                colorbar=dict(
                    title=dict(
                        text=value_label,
                        font=dict(color="#111111"),
                    ),
                    tickfont=dict(color="#111111"),
                    bgcolor="white",
                )
            ),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    
    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"{target_day.date()}",
            font=dict(color="#111111"),
        ),

        width=850,
        height=760,

        margin=dict(l=20, r=20, t=60, b=20),

        plot_bgcolor="white",
        paper_bgcolor="white",

        font=dict(
            color="#111111",
        ),

        hoverlabel=dict(
            bgcolor="white",
            font_color="#111111",
        )
    )

    fig.update_xaxes(range=[0, canvas_w], visible=False)
    fig.update_yaxes(range=[0, canvas_h], visible=False)

    return fig


### Cumulative DLI line chart ###
DLI_LINE_COLORS = [
    "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#10b981",
]


def make_cumulative_dli_plot(df_day, timezone, target_day, wire):
    """Line chart of cumulative DLI through the day, one line per height (one wire)."""
    fig = go.Figure()

    for i, height in enumerate(WIRE_SENSOR_HEIGHTS):
        device = wire_device_id(wire, height)
        cum = compute_cumulative_dli(df_day[df_day["device"] == device])

        if cum is None or cum.empty:
            continue

        label = f"H{height}"
        color = DLI_LINE_COLORS[i % len(DLI_LINE_COLORS)]

        fig.add_trace(
            go.Scatter(
                # Convert UTC → local wall-clock so the axis matches the day shown
                x=cum["time"].dt.tz_convert(timezone).dt.tz_localize(None),
                y=cum["cumulative_dli"],
                name=label,
                mode="lines",
                line=dict(color=color, width=2),
                hovertemplate=(
                    f"<b>{label}</b><br>%{{x|%H:%M}}<br>"
                    "DLI: %{y:.2f} mol/m²<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        title=dict(text=f"Cumulative DLI — {target_day.date()}"),
        height=420,
        hovermode="x unified",
        xaxis_title="Time of day",
        yaxis_title="Cumulative DLI (mol/m²)",
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig