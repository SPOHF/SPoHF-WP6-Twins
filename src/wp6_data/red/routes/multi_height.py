import html
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import pandas as pd  # type: ignore[import-untyped]
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
)
from ..multi_height.assets import CROP_CLIMATE_JS, CROP_CLIMATE_STYLE
from ..multi_height.cells import (
    CROP_ROW_HEIGHT,
    DERIVED_COLUMNS,
    DERIVED_HEADER_ACCENTS,
    MEASUREMENT_COLORS,
    PLANT_SVG_PATH,
    WIRE_MEASUREMENT_LABELS,
    admin_build_panel,
    audit_table,
    fmt_local,
    fungal_cell_from_values,
    height_dli_cell_from_values,
    measurement_cell,
    pill_row,
    plant_zone_cell,
    section_label_cell,
    vpd_cell_from_values,
)
from ..multi_height.charts import (
    detail_chart,
    make_cumulative_dli_plot,
    make_mh_greenhouse_plot,
    make_wire_measurement_plot,
    risk_gantt,
)
from ..multi_height.data import (
    compute_sensor_metrics,
    day_window_utc,
    filter_for_day,
    latest_wire_date,
    load_wire_readings,
    load_wire_sensor_data,
)
from ..multi_height.svg import SVG_LAYOUT_PATH, parse_svg
from ..multi_height.view_model import assemble_crop_climate_day
from ..risk import service, store
from ..risk.config import load_risk_thresholds
from ..utils import svg_to_data_uri
from ..wires import wire_ids

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
    wire_pills = pill_row(
        base, "wire", [(w, w) for w in wires], wire,
        {"measurement": measurement, "date": date_str},
        label="Device",
    )
    measurement_pills = pill_row(
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
    )


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

    wire_pills = pill_row(
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


### Crop Climate by Height ###
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
    risk_t = load_risk_thresholds(deps._METADATA_PATH)

    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    # Default to the latest day this wire actually reported (the feed can lag) —
    # found via a cheap aggregate, not by scanning the table.
    if day is not None:
        target_date = day
    else:
        target_date = await latest_wire_date(wire, timezone)

    # Bound the fetch to the shown day plus the fungal look-back window, so we
    # never scan the whole wire_sensors table per request and wet-hours can
    # accumulate across the prior night.
    fetch_start, fetch_end = day_window_utc(
        target_date or date.today(), timezone, risk_t.fungal.window_hours,
    )
    df = await load_wire_readings(fetch_start, fetch_end)

    # The view-model computes each section's live series once; the persisted
    # per-section state drives the Status badges ("as of last build").
    vm = await assemble_crop_climate_day(
        get_pool(), df, wire, sections, risk_t, timezone, target_date=target_date,
    )
    target_day = vm.day_start

    measured_headers = "".join(
        f'<th style="padding:0.5rem 0.75rem;text-align:left;'
        f'border-bottom:3px solid {MEASUREMENT_COLORS[m]};">'
        f"{WIRE_MEASUREMENT_LABELS[m][0]}</th>"
        for m in WIRE_SENSOR_MEASUREMENTS
    )
    derived_headers = "".join(
        f'<th style="padding:0.5rem 0.75rem;text-align:left;{DERIVED_HEADER_ACCENTS[h]}">'
        f"{h}</th>"
        for h in DERIVED_COLUMNS
    )

    plant_uri = svg_to_data_uri(PLANT_SVG_PATH)

    # Each row: section label | measured cells | plant zone | derived cells | status.
    rows_html = ""
    for i, section in enumerate(vm.sections):
        h = section.height
        measured = "".join(
            measurement_cell(
                section.series[m], m, *vm.bounds[m], h,
                co2_floor=risk_t.co2.floor_ppm,
            )
            for m in WIRE_SENSOR_MEASUREMENTS
        )
        derived = (
            height_dli_cell_from_values(section.height_dli, h)
            + vpd_cell_from_values(
                section.vpd, risk_t.vpd.band_min_kpa, risk_t.vpd.band_max_kpa, h,
            )
            + fungal_cell_from_values(section.fungal, h)
        )
        label_cell = section_label_cell(
            section, vm.state_by_height.get(h),
            risk_t.vpd.band_min_kpa, risk_t.vpd.band_max_kpa,
        )
        rows_html += (
            f"<tr style='border-top:1px solid #e5e7eb;height:{CROP_ROW_HEIGHT}px;'>"
            f"{plant_zone_cell(i, len(vm.sections), plant_uri)}"
            f"{label_cell}{measured}{derived}</tr>"
        )

    table_date = target_day.date().isoformat()
    table = (
        f'<table data-wire="{wire}" data-date="{table_date}" '
        'style="width:100%;border-collapse:collapse;">'
        "<thead><tr>"
        '<th style="width:90px;text-align:center;">Plant</th>'
        '<th style="padding:0.5rem 0.75rem;text-align:left;">Growth section</th>'
        f"{measured_headers}"
        f"{derived_headers}"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
    )

    wire_pills = pill_row(
        "/multi_height/crop-climate", "wire", [(w, w) for w in wires], wire,
        {"date": day.isoformat() if day else None}, label="Device",
    )
    date_form = _date_form("/multi_height/crop-climate", target_day.date(), wire)
    admin_panel = admin_build_panel(wire, target_day.date()) if is_admin(request) else ""
    asof_note = (
        f" · risk as of {fmt_local(vm.as_of, timezone)}" if vm.as_of is not None
        else " · risk log not built yet"
    )

    # Day's risk timeline: episodes overlapping the shown day (so a risk active
    # at midnight shows even though it began the night before). Clamp the query
    # to this local day; the Gantt clamps each bar to the same window.
    ep_start_utc = target_day.tz_convert("UTC").to_pydatetime()
    ep_end_utc = (target_day + pd.Timedelta(days=1)).tz_convert("UTC").to_pydatetime()
    episodes = await store.read_episodes_overlapping(
        get_pool(), wire, ep_start_utc, ep_end_utc,
    )
    gantt_html = risk_gantt(episodes, timezone, target_day)
    if vm.as_of is None:
        gantt_body = '<p style="color:#6b7280;margin:0;">Risk log not built yet.</p>'
    elif gantt_html is None:
        gantt_body = '<p style="color:#16a34a;margin:0;">No risk episodes — clear day ✓</p>'
    else:
        gantt_body = gantt_html
    gantt_card = render_card(
        f"Risk timeline — {table_date}", gantt_body,
        description="One lane per section × risk that fired this day; each bar "
        "spans the period the risk was present.",
        card_class="card",
    )

    content = f"""
    <a href="/multi_height" class="back-link">← Multi Height</a>
    <h1>Crop Climate by Height</h1>
    <p>Measured values are left of the plant, derived metrics on the right.
    Click any cell to expand its chart.</p>

    {wire_pills}
    {date_form}

    {render_card(f"Climate — {table_date}{asof_note}", table, card_class="card")}
    {gantt_card}
    {admin_panel}
    {CROP_CLIMATE_STYLE}
    {CROP_CLIMATE_JS}
    """

    return render_page(
        config.title,
        content,
    )


@router.post(
    "/multi_height/crop-climate/update",
    dependencies=[Depends(verify_session_admin)],
)
async def crop_climate_update(wire: Annotated[str, Form()]):
    """Incrementally extend the wire's risk log up to now (cron stand-in)."""
    if wire not in wire_ids():
        return RedirectResponse(url="/multi_height/crop-climate", status_code=303)

    pool = get_pool()
    now = datetime.now(UTC)
    last = await store.last_built_at(pool, wire)
    start = last or (now - timedelta(days=7))
    # Reach back to subsume any episode still open at the last boundary, so it is
    # recomputed as one span (and closed if resolved) rather than split/orphaned.
    floor = await store.open_episode_floor(pool, wire)
    if floor is not None and floor < start:
        start = floor
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
    if wire not in wire_ids():
        return RedirectResponse(url="/multi_height/crop-climate", status_code=303)

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

    wire_pills = pill_row(
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
    {render_card("Episodes", audit_table(episodes, tz), card_class="card")}
    """
    return render_page(
        config.title,
        content,
    )


### Crop-climate cell detail chart (click-to-expand) ###
# Metrics the chart endpoint will serve (measured + derived); anything else 400s.
CROP_CHART_METRICS = (*WIRE_SENSOR_MEASUREMENTS, "dli", "vpd", "fungal")


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

    # Validate against allowlists — these params arrive from client-built URLs.
    if metric not in CROP_CHART_METRICS or height not in WIRE_SENSOR_HEIGHTS:
        return HTMLResponse(
            '<p style="font:14px sans-serif;padding:1rem;color:#b91c1c;">'
            "Unknown chart.</p>",
            status_code=400,
        )

    wires = wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    risk_t = load_risk_thresholds(deps._METADATA_PATH)
    # Bound the fetch to the shown day plus the fungal look-back (no table scan).
    fetch_start, fetch_end = day_window_utc(
        day or date.today(), timezone, risk_t.fungal.window_hours,
    )
    day_start = pd.Timestamp(day or date.today(), tz=timezone)
    df = await load_wire_readings(fetch_start, fetch_end)
    hdf = df[df["device"] == wire_device_id(wire, height)] if not df.empty else df

    fig = detail_chart(hdf, metric, timezone, risk_t, day_start)
    return HTMLResponse(
        fig.to_html(
            full_html=True, include_plotlyjs="cdn",
            config={"responsive": True, "displaylogo": False},
        )
    )
