import html
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wp6_data.db.pool import get_pool
from wp6_data.shared import render_card, render_hub_card, render_hub_grid, render_page
from wp6_data.shared.auth import is_admin, verify_session_admin, verify_session_user
from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

from .. import deps
from ..db import (
    WIRE_SENSOR_HEIGHTS,
    WIRE_SENSOR_MEASUREMENTS,
    wire_device_id,
    wire_physical_id,
)
from ..risk import service, store
from ..risk.config import load_risk_thresholds
from ..risk.metrics import (
    compute_cumulative_dli,
    compute_dli,
    vpd_series,
    wet_hours_series,
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
    {
        "href": "/multi_height/crop-climate",
        "title": "Crop Climate by Height",
        "label": "Open view",
        "description": "Per growth section (canopy top to root zone): the day's "
        "PAR, temperature, humidity and CO₂ as compact trends.",
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


### Crop Climate by Height ###
# A per-growth-section climate table: one row per growth section (H1 top → H5
# root, ordered from red config), one column per raw measurement type. The grid
# is dense (5×4 trends), so cells use lightweight inline-SVG sparklines (no
# per-cell plotly) plus the latest value.
MEASUREMENT_COLORS = {
    "par": "#f59e0b",
    "temp": "#ef4444",
    "hum": "#06b6d4",
    "co2": "#8b5cf6",
}

# The plant rail is a single rowspanned SVG; aligning it to rows means each body
# row is exactly CROP_ROW_HEIGHT tall and the SVG is len(sections) * that.
CROP_ROW_HEIGHT = 72
PLANT_SVG_PATH = Path(__file__).parent.parent / "static/crop_plant.svg"

# Row-expansion: clicking a cell inserts a detail <tr> with an <iframe> chart
# (lazy-loaded from the chart endpoint). One detail row at a time; clicking the
# same cell again collapses it. Plain string (no f-string) to keep JS braces.
CROP_CLIMATE_JS = """
<script>
function ccChart(td){
  var table = td.closest('table'), tr = td.closest('tr');
  var key = tr.rowIndex + ':' + td.dataset.height + ':' + td.dataset.metric;
  var open = table.querySelector('tr.cc-detail');
  var same = open && open.dataset.key === key;
  if (open) open.remove();
  if (same) return;
  var dr = document.createElement('tr');
  dr.className = 'cc-detail'; dr.dataset.key = key;
  var cell = document.createElement('td');
  cell.colSpan = table.rows[0].cells.length; cell.style.padding = '0';
  var ifr = document.createElement('iframe');
  ifr.style.cssText = 'width:100%;height:400px;border:0;background:#fff;border-radius:8px;';
  ifr.srcdoc = '<p style="font:14px sans-serif;padding:1rem;color:#555;">Loading chart…</p>';
  cell.appendChild(ifr); dr.appendChild(cell);
  tr.parentNode.insertBefore(dr, tr.nextSibling);
  var q = new URLSearchParams({wire: table.dataset.wire, date: table.dataset.date,
                               height: td.dataset.height, metric: td.dataset.metric});
  fetch('/multi_height/crop-climate/chart?' + q.toString())
    .then(function(r){ return r.text(); })
    .then(function(h){ ifr.srcdoc = h; })
    .catch(function(){ ifr.srcdoc =
      '<p style="font:14px sans-serif;padding:1rem;color:#b91c1c;">Failed to load chart.</p>'; });
}
</script>
"""


def _plant_zone_cell(index: int, total: int, uri: str) -> str:
    """Center separator: this row's vertical slice of the plant SVG.

    The full SVG is cropped to the row's zone via a negative offset, so the rows
    together reconstruct the whole plant while each row stays independent — that
    lets a detail row expand between rows without breaking a rowspan. The plant
    sits between the measured (left) and derived (right) columns.
    """
    return (
        '<td style="padding:0;width:90px;vertical-align:middle;">'
        f'<div style="height:{CROP_ROW_HEIGHT}px;width:80px;overflow:hidden;'
        'margin:auto;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;">'
        f'<img src="{uri}" width="80" height="{total * CROP_ROW_HEIGHT}" '
        f'style="display:block;margin-top:-{index * CROP_ROW_HEIGHT}px;"></div></td>'
    )


def _sparkline_svg(values, color, width=96, height=28):
    """Minimal inline-SVG sparkline (no JS), self-normalised to its own range."""
    pts = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(pts) < 2:
        return '<span style="color:#9ca3af;">—</span>'
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    last = len(pts) - 1
    coords = " ".join(
        f"{(i / last) * (width - 2) + 1:.1f},"
        f"{height - 1 - ((v - lo) / span) * (height - 2):.1f}"
        for i, v in enumerate(pts)
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'style="display:block;">'
        f'<polyline points="{coords}" fill="none" stroke="{color}" '
        'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _series_for(df_day, device, measurement):
    """Time-sorted value list for one height-device + measurement on the day."""
    if df_day.empty:
        return []
    d = df_day[
        (df_day["device"] == device) & (df_day["measurement"] == measurement)
    ].sort_values("time")
    return d["value"].tolist()


def _cell_open(height, metric, extra_style="") -> str:
    """Opening <td> for a clickable cell (expands a line chart on click)."""
    return (
        f'<td data-height="{height}" data-metric="{metric}" '
        'onclick="ccChart(this)" title="Click to expand a chart" '
        f'style="padding:0.5rem 0.75rem;vertical-align:middle;cursor:pointer;{extra_style}">'
    )


def _measurement_cell(series, measurement, vmin, vmax, height):
    """A clickable measured cell: latest value (+ unit) above the day's sparkline.

    Background is a relative tint (white→measurement-colour by rank within the
    column), so colour means "high/low vs the other heights", never an absolute
    threshold. Clicking expands a line chart for this height + measurement.
    """
    _, unit = WIRE_MEASUREMENT_LABELS[measurement]
    latest = series[-1] if series else None
    value = "—" if latest is None else f"{_format_reading(latest)} {unit}"
    scale = [[0.0, "#ffffff"], [1.0, MEASUREMENT_COLORS[measurement]]]
    bg = value_to_color(latest, vmin, vmax, colorscale=scale, alpha=0.5)
    return (
        _cell_open(height, measurement, f"background:{bg};")
        + f'<div style="font-weight:600;font-size:0.9rem;">{value}</div>'
        + _sparkline_svg(series, MEASUREMENT_COLORS[measurement])
        + "</td>"
    )


### Derived risk columns (issue 016) — threshold-free trends, computed on read ###
HEIGHT_DLI_COLOR = "#16a34a"
FUNGAL_COLOR = "#7c3aed"
VPD_LINE_COLOR = "#0ea5e9"
DERIVED_COLUMNS = ["Height DLI", "VPD", "Fungal risk"]


def _derived_cell(value: str, spark: str, height, metric: str) -> str:
    return (
        _cell_open(height, metric)
        + f'<div style="font-weight:600;font-size:0.9rem;">{value}</div>{spark}</td>'
    )


def _vpd_sparkline_svg(values, band_min, band_max, width=96, height=28):
    """VPD sparkline on a fixed 0..max scale with the healthy band shaded.

    Unlike the self-normalising raw sparkline, this fixes the y-domain so the
    band rectangle is stable across cells and excursions read consistently.
    """
    pts = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(pts) < 2:
        return '<span style="color:#9ca3af;">—</span>'
    vmax = (max(max(pts), band_max) * 1.05) or 1.0
    last = len(pts) - 1

    def _y(val):
        return height - 1 - (val / vmax) * (height - 2)

    band_top = _y(band_max)
    band_h = max(0.0, _y(band_min) - band_top)
    coords = " ".join(
        f"{(i / last) * (width - 2) + 1:.1f},{_y(v):.1f}" for i, v in enumerate(pts)
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'style="display:block;">'
        f'<rect x="0" y="{band_top:.1f}" width="{width}" height="{band_h:.1f}" '
        'fill="#16a34a" opacity="0.15"/>'
        f'<polyline points="{coords}" fill="none" stroke="{VPD_LINE_COLOR}" '
        'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _height_dli_cell(par_df, height):
    cum = compute_cumulative_dli(par_df)
    if cum is None or cum.empty:
        return _derived_cell("—", _sparkline_svg([], HEIGHT_DLI_COLOR), height, "dli")
    values = cum["cumulative_dli"].tolist()
    return _derived_cell(
        f"{values[-1]:.1f} mol", _sparkline_svg(values, HEIGHT_DLI_COLOR), height, "dli"
    )


def _vpd_cell(height_df, band_min, band_max, height):
    v = vpd_series(height_df)
    if v.empty:
        return _derived_cell("—", '<span style="color:#9ca3af;">—</span>', height, "vpd")
    values = v["value"].tolist()
    return _derived_cell(
        f"{values[-1]:.2f} kPa", _vpd_sparkline_svg(values, band_min, band_max),
        height, "vpd",
    )


def _fungal_cell(hum_df, rh_pct, window_hours, height):
    w = wet_hours_series(hum_df, rh_pct, window_hours)
    if w.empty:
        return _derived_cell("—", _sparkline_svg([], FUNGAL_COLOR), height, "fungal")
    values = w["value"].tolist()
    return _derived_cell(
        f"{values[-1]:.1f} h", _sparkline_svg(values, FUNGAL_COLOR), height, "fungal"
    )


def _section_label_cell(section, state=None):
    """Growth-section label, with any active-risk badges beneath it."""
    badges = _section_badges(state)
    badge_html = f'<div style="margin-top:4px;">{badges}</div>' if badges else ""
    return (
        '<td style="padding:0.5rem 0.75rem;font-weight:600;white-space:nowrap;">'
        f'<span style="color:#6b7280;">H{section.height}</span> · '
        f"{html.escape(section.label)}{badge_html}</td>"
    )


def _date_form(base_path: str, day: date, wire: str) -> str:
    """Single-date picker that GETs back to this view (keeps the wire)."""
    return f"""
    <form method="get" action="{base_path}" style="display:flex;gap:12px;
        align-items:flex-end;margin-bottom:16px;flex-wrap:wrap;">
        <input type="hidden" name="wire" value="{wire}">
        <label>Date<br>
            <input type="date" name="date" value="{day.isoformat()}">
        </label>
        <button type="submit">Update</button>
    </form>
    """


@router.get("/multi_height/crop-climate", response_class=HTMLResponse)
async def crop_climate_page(
    request: Request,
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    day: Annotated[
        date | None,
        Query(alias="date", description="Day to view (YYYY-MM-DD); defaults to latest with data"),
    ] = None,
    wire: Annotated[
        str | None, Query(description="Which wire to show; defaults to the first declared")
    ] = None,
):
    timezone = deps.base_settings.display_timezone
    sections = deps.growth_sections

    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    df = await load_wire_readings()
    wire_devices = [wire_device_id(wire, s.height) for s in sections]

    # Default to the latest day this wire actually reported (the feed can lag).
    if day is not None:
        target_date = day
    else:
        scoped = df[df["device"].isin(wire_devices)] if not df.empty else df
        target_date = (
            scoped["time"].dt.tz_convert(timezone).max().date()
            if not scoped.empty else None
        )

    df_day, target_day = filter_for_day(df, timezone, target_date=target_date)

    # Persisted per-section state drives the Status column ("as of last build").
    state_by_height = {r["height"]: r for r in await store.read_state(get_pool(), wire)}
    as_of = max((r["built_at"] for r in state_by_height.values()), default=None)

    measured_headers = "".join(
        f'<th style="padding:0.5rem 0.75rem;text-align:left;">'
        f"{WIRE_MEASUREMENT_LABELS[m][0]}</th>"
        for m in WIRE_SENSOR_MEASUREMENTS
    )
    derived_headers = "".join(
        f'<th style="padding:0.5rem 0.75rem;text-align:left;">{h}</th>'
        for h in DERIVED_COLUMNS
    )

    # Day's series per (height, measurement), computed once; per-column bounds
    # (latest value across the five heights) drive the relative cell tint.
    series_map = {
        (section.height, m): _series_for(df_day, wire_device_id(wire, section.height), m)
        for section in sections
        for m in WIRE_SENSOR_MEASUREMENTS
    }
    col_bounds = {}
    for m in WIRE_SENSOR_MEASUREMENTS:
        latests = [
            series_map[(section.height, m)][-1]
            for section in sections
            if series_map[(section.height, m)]
        ]
        col_bounds[m] = (min(latests), max(latests)) if latests else (0.0, 1.0)

    risk_t = load_risk_thresholds(deps._METADATA_PATH)
    plant_uri = svg_to_data_uri(PLANT_SVG_PATH)

    # Each row: section label | measured cells | plant zone | derived cells | status.
    rows_html = ""
    for i, section in enumerate(sections):
        h = section.height
        device = wire_device_id(wire, h)
        measured = "".join(
            _measurement_cell(series_map[(h, m)], m, *col_bounds[m], h)
            for m in WIRE_SENSOR_MEASUREMENTS
        )
        hdf = df_day[df_day["device"] == device]
        par_df = hdf[hdf["measurement"] == "par"][["time", "value"]]
        hum_df = hdf[hdf["measurement"] == "hum"][["time", "value"]]
        derived = (
            _height_dli_cell(par_df, h)
            + _vpd_cell(hdf, risk_t.vpd.band_min_kpa, risk_t.vpd.band_max_kpa, h)
            + _fungal_cell(hum_df, risk_t.fungal.rh_pct, risk_t.fungal.window_hours, h)
        )
        rows_html += (
            f"<tr style='border-top:1px solid #e5e7eb;height:{CROP_ROW_HEIGHT}px;'>"
            f"{_section_label_cell(section, state_by_height.get(h))}{measured}"
            f"{_plant_zone_cell(i, len(sections), plant_uri)}"
            f"{derived}</tr>"
        )

    table_date = target_day.date().isoformat()
    table = (
        f'<table data-wire="{wire}" data-date="{table_date}" '
        'style="width:100%;border-collapse:collapse;">'
        "<thead><tr>"
        '<th style="padding:0.5rem 0.75rem;text-align:left;">Growth section</th>'
        f"{measured_headers}"
        '<th style="width:90px;text-align:center;">Plant</th>'
        f"{derived_headers}"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
    )

    wire_pills = _pill_row(
        "/multi_height/crop-climate", "wire", [(w, w) for w in wires], wire,
        {"date": day.isoformat() if day else None}, label="Device",
    )
    date_form = _date_form("/multi_height/crop-climate", target_day.date(), wire)
    admin_panel = _admin_build_panel(wire, target_day.date()) if is_admin(request) else ""
    asof_note = (
        f" · risk as of {as_of:%Y-%m-%d %H:%M} UTC" if as_of is not None
        else " · risk log not built yet"
    )

    content = f"""
    <a href="/multi_height" class="back-link">← Multi Height</a>
    <h1>Crop Climate by Height</h1>
    <p>Measured values are left of the plant, derived metrics on the right.
    Click any cell to expand its chart.</p>

    {wire_pills}
    {date_form}

    {render_card(f"Climate — {table_date}{asof_note}", table, card_class="card")}
    {admin_panel}
    {CROP_CLIMATE_JS}
    """

    return render_page(
        config.title,
        content,
        data_source=provider.data_source_label,
    )


### Risk verdict + admin build (issue 015) ###
def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#fff;border-radius:6px;'
        f'padding:2px 8px;font-size:0.8rem;margin-right:4px;">{text}</span>'
    )


def _section_badges(state) -> str:
    """Active-risk badges for a section from its persisted state (no recompute).

    Only *active* risks render — no "OK" or placeholder, so a healthy section
    stays clean. Empty string when ``state`` is absent or nothing is flagged.
    """
    if not state:
        return ""
    badges = []
    if state.get("canopy_deficit"):
        badges.append(_badge("Light", "#b45309"))
    if state.get("fungal_active"):
        badges.append(_badge("Fungal", "#7c3aed"))
    if state.get("vpd_in_band") is False:
        badges.append(_badge("VPD", "#b91c1c"))
    return "".join(badges)


def _admin_build_panel(wire: str, day: date) -> str:
    """Admin-only Update (to now) + Rebuild (date range) build controls."""
    update_form = (
        '<form method="post" action="/multi_height/crop-climate/update" '
        'style="display:inline;">'
        f'<input type="hidden" name="wire" value="{wire}">'
        '<button type="submit">Update (to now)</button></form>'
    )
    rebuild_form = (
        '<form method="post" action="/multi_height/crop-climate/rebuild" '
        'style="display:flex;gap:8px;align-items:flex-end;margin-top:8px;'
        'flex-wrap:wrap;">'
        f'<input type="hidden" name="wire" value="{wire}">'
        f'<label>From<br><input type="date" name="start" value="{day.isoformat()}"></label>'
        f'<label>To<br><input type="date" name="end" value="{day.isoformat()}"></label>'
        '<button type="submit">Rebuild range</button></form>'
    )
    audit_link = (
        '<p style="margin-top:10px;">'
        f'<a href="/multi_height/crop-climate/audit?wire={wire}">Open risk log →</a>'
        "</p>"
    )
    return render_card(
        "Admin — build risk log",
        update_form + rebuild_form + audit_link,
        description="Update extends the log to now; Rebuild recomputes a date "
        "range from raw data. Runs on demand.",
        card_class="card",
    )


@router.post(
    "/multi_height/crop-climate/update",
    dependencies=[Depends(verify_session_admin)],
)
async def crop_climate_update(wire: Annotated[str, Form()]):
    """Incrementally extend the wire's risk log up to now (cron stand-in)."""
    now = datetime.now(UTC)
    last = await store.last_built_at(get_pool(), wire)
    start = last or (now - timedelta(days=7))
    await service.build_range(wire, start, now)
    return RedirectResponse(
        url=f"/multi_height/crop-climate?wire={wire}", status_code=303,
    )


@router.post(
    "/multi_height/crop-climate/rebuild",
    dependencies=[Depends(verify_session_admin)],
)
async def crop_climate_rebuild(
    wire: Annotated[str, Form()],
    start: Annotated[date, Form()],
    end: Annotated[date, Form()],
):
    """Recompute the wire's risk log over a selectable date range."""
    tz = deps.base_settings.display_timezone
    start_utc = pd.Timestamp(start, tz=tz).tz_convert("UTC").to_pydatetime()
    end_utc = (
        (pd.Timestamp(end, tz=tz) + pd.Timedelta(days=1))
        .tz_convert("UTC")
        .to_pydatetime()
    )
    await service.build_range(wire, start_utc, end_utc)
    return RedirectResponse(
        url=f"/multi_height/crop-climate?wire={wire}", status_code=303,
    )


### Risk-episode audit log (issue 018) ###
RISK_LABELS = {
    "vpd": "VPD out of band",
    "fungal": "Fungal risk",
    "canopy": "Canopy light deficit",
}


def _fmt_duration(td) -> str:
    """Human duration like '1d 3h' / '2h 30m' / '45m'."""
    total = int(td.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def _audit_table(episodes) -> str:
    """Render persisted risk episodes (cache dicts) as an HTML table."""
    if not episodes:
        return (
            '<p style="color:#6b7280;">No risk episodes in this range — build the '
            "log from the Crop Climate page first.</p>"
        )
    headers = ("Section", "Risk", "Present from", "Resolved", "Duration", "Peak",
               "Thresholds")
    head = "<thead><tr>" + "".join(
        f'<th style="padding:0.4rem 0.75rem;text-align:left;">{h}</th>'
        for h in headers
    ) + "</tr></thead>"

    rows = ""
    for e in episodes:
        start, end = e["start_time"], e["end_time"]
        resolved = (
            f"{end:%Y-%m-%d %H:%M} UTC" if end is not None
            else '<em style="color:#b45309;">ongoing</em>'
        )
        duration = _fmt_duration(end - start) if end is not None else "—"
        cells = [
            f'H{e["height"]} {html.escape(e["label"])}',
            html.escape(RISK_LABELS.get(e["risk"], e["risk"])),
            f"{start:%Y-%m-%d %H:%M} UTC",
            resolved,
            duration,
            f'{e["peak"]:.2f}',
            f'<code style="font-size:0.8rem;">{html.escape(str(e["thresholds"]))}</code>',
        ]
        rows += (
            "<tr style='border-top:1px solid #e5e7eb;'>"
            + "".join(f'<td style="padding:0.4rem 0.75rem;">{c}</td>' for c in cells)
            + "</tr>"
        )
    return (
        '<table style="width:100%;border-collapse:collapse;">'
        f"{head}<tbody>{rows}</tbody></table>"
    )


@router.get(
    "/multi_height/crop-climate/audit",
    response_class=HTMLResponse,
    dependencies=[Depends(verify_session_admin)],
)
async def crop_climate_audit(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[
        date | None, Query(description="Range start (YYYY-MM-DD); default 7 days ago")
    ] = None,
    end: Annotated[
        date | None, Query(description="Range end (YYYY-MM-DD); default today")
    ] = None,
    wire: Annotated[
        str | None, Query(description="Which wire; default first declared")
    ] = None,
):
    tz = deps.base_settings.display_timezone
    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    end_day = end or date.today()
    start_day = start or (end_day - timedelta(days=7))
    start_utc = pd.Timestamp(start_day, tz=tz).tz_convert("UTC").to_pydatetime()
    end_utc = (
        (pd.Timestamp(end_day, tz=tz) + pd.Timedelta(days=1))
        .tz_convert("UTC")
        .to_pydatetime()
    )

    episodes = await store.read_episodes(get_pool(), wire, start_utc, end_utc)

    wire_pills = _pill_row(
        "/multi_height/crop-climate/audit", "wire", [(w, w) for w in wires], wire,
        {"start": start_day.isoformat(), "end": end_day.isoformat()}, label="Device",
    )
    content = f"""
    <a href="/multi_height/crop-climate?wire={wire}" class="back-link">← Crop Climate</a>
    <h1>Risk Log — {wire}</h1>
    <p>Persisted risk episodes for the selected range. Each row states the
    threshold-set that produced it — a Rebuild under different thresholds
    rewrites these.</p>

    {wire_pills}
    {_wire_range_form(start_day, end_day, wire)}
    {render_card("Episodes", _audit_table(episodes), card_class="card")}
    """
    return render_page(
        config.title,
        content,
        data_source=provider.data_source_label,
    )


### Crop-climate cell detail chart (click-to-expand) ###
def _detail_chart(hdf, metric, timezone, risk_t):
    """Full line chart for one height + metric over the day (row expansion)."""
    fig = go.Figure()
    title, ytitle = metric, ""

    def _local(s):
        return s.dt.tz_convert(timezone).dt.tz_localize(None)

    if metric in WIRE_SENSOR_MEASUREMENTS:
        label, unit = WIRE_MEASUREMENT_LABELS[metric]
        d = hdf[hdf["measurement"] == metric].sort_values("time")
        if not d.empty:
            fig.add_trace(go.Scatter(
                x=_local(d["time"]), y=d["value"], mode="lines",
                line=dict(color=MEASUREMENT_COLORS[metric], width=2), name=label,
            ))
        title, ytitle = label, f"{label} ({unit})"
    elif metric == "dli":
        cum = compute_cumulative_dli(hdf[hdf["measurement"] == "par"][["time", "value"]])
        if cum is not None and not cum.empty:
            fig.add_trace(go.Scatter(
                x=_local(cum["time"]), y=cum["cumulative_dli"], mode="lines",
                line=dict(color=HEIGHT_DLI_COLOR, width=2), name="Height DLI",
            ))
        fig.add_hline(y=risk_t.canopy_dli.target_mol, line_dash="dot",
                      line_color=HEIGHT_DLI_COLOR, annotation_text="target")
        title, ytitle = "Cumulative Height DLI", "mol/m²"
    elif metric == "vpd":
        v = vpd_series(hdf)
        if not v.empty:
            fig.add_trace(go.Scatter(
                x=_local(v["time"]), y=v["value"], mode="lines",
                line=dict(color=VPD_LINE_COLOR, width=2), name="VPD",
            ))
        fig.add_hrect(y0=risk_t.vpd.band_min_kpa, y1=risk_t.vpd.band_max_kpa,
                      fillcolor="#16a34a", opacity=0.12, line_width=0)
        title, ytitle = "VPD vs healthy band", "kPa"
    elif metric == "fungal":
        w = wet_hours_series(
            hdf[hdf["measurement"] == "hum"][["time", "value"]],
            risk_t.fungal.rh_pct, risk_t.fungal.window_hours,
        )
        if not w.empty:
            fig.add_trace(go.Scatter(
                x=_local(w["time"]), y=w["value"], mode="lines",
                line=dict(color=FUNGAL_COLOR, width=2), name="Wet-hours",
            ))
        fig.add_hline(y=risk_t.fungal.active_wet_hours, line_dash="dot",
                      line_color=FUNGAL_COLOR, annotation_text="active")
        title, ytitle = "Fungal risk (wet-hours)", "hours"

    fig.update_layout(
        template="plotly_white", height=380, title=title,
        xaxis_title="Time of day", yaxis_title=ytitle, hovermode="x unified",
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


@router.get("/multi_height/crop-climate/chart", response_class=HTMLResponse)
async def crop_climate_chart(
    height: Annotated[int, Query(description="Wire height 1-5")],
    metric: Annotated[str, Query(description="par/temp/hum/co2/dli/vpd/fungal")],
    wire: Annotated[
        str | None, Query(description="Which wire; default first declared")
    ] = None,
    day: Annotated[date | None, Query(alias="date", description="Day (YYYY-MM-DD)")] = None,
):
    """Standalone line chart for one cell, served into the row-expansion iframe."""
    timezone = deps.base_settings.display_timezone
    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    df = await load_wire_readings()
    df_day, _ = filter_for_day(df, timezone, target_date=day)
    hdf = df_day[df_day["device"] == wire_device_id(wire, height)]

    risk_t = load_risk_thresholds(deps._METADATA_PATH)
    fig = _detail_chart(hdf, metric, timezone, risk_t)
    return HTMLResponse(
        fig.to_html(
            full_html=True, include_plotlyjs="cdn",
            config={"responsive": True, "displaylogo": False},
        )
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