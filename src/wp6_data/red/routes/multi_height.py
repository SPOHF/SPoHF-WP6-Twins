import html
import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import pandas as pd  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wp6_data.db.pool import get_pool
from wp6_data.shared import pill_row, render_card, render_hub_card, render_hub_grid, render_page
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
    METRIC_LABELS,
    PLANT_SVG_PATH,
    WIRE_MEASUREMENT_LABELS,
    admin_build_panel,
    audit_table,
    fmt_local,
    fungal_cell_from_values,
    height_dli_cell_from_values,
    measurement_cell,
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
    wire_profile_chart,
)
from ..multi_height.config import CROP_METRICS, load_uniformity_config
from ..multi_height.data import (
    compute_sensor_metrics,
    day_window_utc,
    filter_for_day,
    latest_reading_time,
    latest_reporting_date,
    latest_wire_date,
    load_wire_readings,
)
from ..multi_height.side_replay import (
    build_frames,
    choose_step,
    frame_index_at,
    frame_times,
    resolve_window,
    shared_scale,
    stale_after,
)
from ..multi_height.side_section import (
    DEFAULT_STYLE,
    MEASUREMENT_STYLES,
    PlacedNode,
    latest_node_readings,
    place_nodes,
    render_replay_svg,
    render_side_svg,
)
from ..multi_height.svg import (
    SECTION_LAYOUT_PATH,
    SVG_LAYOUT_PATH,
    SectionLayout,
    parse_section_layout,
    parse_svg,
)
from ..multi_height.uniformity import build_uniformity_day
from ..multi_height.uniformity_cells import (
    aggregate_phrase,
    spread_legend,
    uniformity_table,
    verdict_list,
)
from ..multi_height.view_model import assemble_crop_climate_day
from ..risk import service, store
from ..risk.config import load_risk_thresholds
from ..utils import svg_to_data_uri
from ..wires import wire_ids

router = APIRouter(dependencies=[Depends(verify_session_user)])

# Views available under the Multi Height section. Each entry becomes a hub card
# on the landing page below. Add more here as additional height views are built.
# Temperature leads the uniformity view: it is the metric most likely to differ
# with where a wire hangs, so it is the one that shows the page working.
DEFAULT_UNIFORMITY_METRIC = "temp"
DEFAULT_SECTION_MEASUREMENT = "temp"

MULTI_HEIGHT_VIEWS = [
    {
        "href": "/multi_height/single-simple",
        "title": "Simple Greenhouse View",
        "label": "Open view",
        "description": "Latest PAR and Daily Light Integral mapped onto the "
        "greenhouse layout at each sensor height.",
    },
    {
        "href": "/multi_height/side-section",
        "title": "Side Section of Wires",
        "label": "Open view",
        "description": "Latest PAR, temperature, humidity and CO₂ at every height of "
        "every wire, as a cross-section of the greenhouse.",
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
    {
        "href": "/climate/forecast",
        "title": "Climate Forecast by Section",
        "label": "Open view",
        "description": "The same growth sections 48 hours ahead: predicted "
        "temperature, humidity and CO₂ against the outdoor conditions, with "
        "the held-out error the prediction was measured at.",
    },
    {
        "href": "/multi_height/uniformity",
        "title": "Uniformity across Wires",
        "label": "Open view",
        "description": "The same growth sections on every declared wire, side "
        "by side — where the greenhouse agrees, and where it doesn't.",
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

    wires = await wire_ids()
    if wire not in wires:
        wire = wires[0] if wires else ""

    timezone = deps.base_settings.display_timezone
    is_par = measurement == "par"

    meta = deps.metadata.sensor_default(measurement)
    label = meta.alias or measurement
    value_label = f"{label} ({meta.unit})" if meta.unit else label

    # Default to the latest day this wire actually reported, not "today" — the
    # wire feed can lag, which would otherwise show empty boxes. Found via a
    # cheap aggregate, not by scanning the table.
    if day is not None:
        target_date = day
    else:
        target_date = await latest_wire_date(wire, timezone)

    # Bound the fetch to the shown day's UTC window. Single-simple has no
    # cross-night metric, so no look-back is needed.
    fetch_start, fetch_end = day_window_utc(target_date or date.today(), timezone, 0)
    df = await load_wire_readings(fetch_start, fetch_end)

    wire_devices = [wire_device_id(wire, h) for h in WIRE_SENSOR_HEIGHTS]

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


async def _latest_section_nodes(
    measurement: str,
) -> tuple[list[PlacedNode], SectionLayout, str]:
    """Each wire's latest ``measurement`` readings, placed in one row."""
    timezone = deps.base_settings.display_timezone
    wires = await wire_ids()

    # Latest *available* data: open on the last day any wire reported, then take
    # each wire's last reading of that day, so a lagging feed never blanks the page.
    target_date = await latest_reporting_date(wires, timezone)
    df = None
    if target_date is not None:
        start, end = day_window_utc(target_date, timezone, 0)
        df = await load_wire_readings(start, end)

    readings = latest_node_readings(df, wires, measurement) if df is not None else {}
    layout = parse_section_layout(SECTION_LAYOUT_PATH)
    return place_nodes(readings, layout), layout, timezone


def _section_measurement_pills(base: str, measurement: str, extra: dict) -> str:
    return pill_row(
        base, "measurement",
        [(m, WIRE_MEASUREMENT_LABELS[m][0]) for m in WIRE_SENSOR_MEASUREMENTS],
        measurement, extra, label="Measurement",
    )


def _section_card(
    nodes: list[PlacedNode], timezone: str, label: str, title: str, render, blurb: str,
) -> str:
    if not any(n.readings for n in nodes):
        body = (
            f'<p style="color:#6b7280;margin:0;">No wire has reported '
            f"{html.escape(label.lower())} yet.</p>"
        )
        stamp = ""
    else:
        body = render()
        latest = max(r.time for n in nodes for r in n.readings.values())
        stamp = (
            " Latest reading: "
            f"{pd.Timestamp(latest).tz_convert(timezone):%Y-%m-%d %H:%M}."
        )
    return render_card(
        f"{html.escape(label)} {title}", body,
        description=blurb + " Wire positions are schematic; the real layout is not known."
        + stamp,
        card_class="card",
    )


REPLAY_JS = """<script>
(function () {
  var root = document.getElementById("replay");
  if (!root) return;
  var slider = root.querySelector("input[type=range]");
  var label = root.querySelector(".replay-time");
  var button = root.querySelector("button.replay-play");
  var frames = JSON.parse(root.getAttribute("data-frames"));
  var timer = null;
  function show(i) {
    document.querySelectorAll("g.rf").forEach(function (g) {
      g.style.display = g.getAttribute("data-i") === String(i) ? "" : "none";
    });
    label.textContent = frames[i].label;
    slider.value = i;
    var url = new URL(window.location.href);
    url.searchParams.set("at", frames[i].at);
    window.history.replaceState(null, "", url);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    button.textContent = "Play";
  }
  button.addEventListener("click", function () {
    if (timer) { stop(); return; }
    if (+slider.value >= frames.length - 1) show(0);
    button.textContent = "Pause";
    timer = setInterval(function () {
      var next = +slider.value + 1;
      if (next >= frames.length) { stop(); return; }
      show(next);
    }, 500);
  });
  slider.addEventListener("input", function () { stop(); show(+slider.value); });
})();
</script>"""


def _parse_local_instant(value: str | None, timezone: str) -> datetime | None:
    """A ``from``/``to``/``at`` value as UTC; wall-clock input is read in ``timezone``."""
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        ts = (
            ts.tz_localize(timezone, ambiguous=True, nonexistent="shift_forward")
            if ts.tzinfo is None
            else ts
        )
        return ts.tz_convert("UTC").to_pydatetime()
    except (ValueError, TypeError, OverflowError):
        return None


def _local_input(ts, timezone: str) -> str:
    return f"{pd.Timestamp(ts).tz_convert(timezone):%Y-%m-%dT%H:%M}"


def _replay_form(start: datetime, end: datetime, measurement: str, timezone: str) -> str:
    return f"""
    <form method="get" action="/multi_height/side-section"
          style="display:flex;gap:.75rem;flex-wrap:wrap;align-items:end;">
        <input type="hidden" name="measurement" value="{html.escape(measurement)}">
        <label>From<br><input type="datetime-local" name="from" required
            value="{_local_input(start, timezone)}"></label>
        <label>To<br><input type="datetime-local" name="to"
            value="{_local_input(end, timezone)}"></label>
        <button type="submit">Replay</button>
        <a href="/multi_height/side-section?measurement={html.escape(measurement)}">Latest</a>
    </form>
    """


def _replay_form_empty(measurement: str) -> str:
    return f"""
    <form method="get" action="/multi_height/side-section"
          style="display:flex;gap:.75rem;flex-wrap:wrap;align-items:end;">
        <input type="hidden" name="measurement" value="{html.escape(measurement)}">
        <label>Replay from<br><input type="datetime-local" name="from" required></label>
        <label>To<br><input type="datetime-local" name="to"></label>
        <button type="submit">Replay</button>
    </form>
    """


async def _replay_card(
    window: tuple[datetime, datetime],
    at: datetime | None,
    measurement: str,
    wires: list[str],
    timezone: str,
) -> str:
    start, end = window
    label, unit = WIRE_MEASUREMENT_LABELS[measurement]
    step = choose_step(end - start)
    stale = stale_after(step)
    times = frame_times(start, end, step)

    # One query over the window (plus the look-back that feeds the first frames).
    df = await load_wire_readings(
        start - stale, end + timedelta(seconds=1),
    )
    frames = build_frames(df, wires, measurement, times, stale)
    layout = parse_section_layout(SECTION_LAYOUT_PATH)
    placed = [place_nodes(f.readings, layout) for f in frames]
    if not any(f.readings[w] for f in frames for w in f.readings):
        return render_card(
            f"{html.escape(label)} side section replay",
            f'<p style="color:#6b7280;margin:0;">No wire reported {html.escape(label.lower())} '
            "in this window.</p>",
            card_class="card",
        )

    style = MEASUREMENT_STYLES.get(measurement, DEFAULT_STYLE)
    scale = shared_scale(placed, style)
    selected = frame_index_at(times, at)
    svg = render_replay_svg(placed, layout, measurement, label, unit, scale, selected)
    meta = json.dumps([
        {"label": f"{t.tz_convert(timezone):%Y-%m-%d %H:%M}", "at": _local_input(t, timezone)}
        for t in times
    ]).replace("<", "\\u003c")
    controls = f"""
    <div id="replay" data-frames='{html.escape(meta, quote=True)}'
         style="display:flex;gap:1rem;align-items:center;margin:.5rem 0;">
        <button type="button" class="replay-play">Play</button>
        <input type="range" min="0" max="{len(times) - 1}" value="{selected}"
               style="flex:1;" aria-label="Frame">
        <strong class="replay-time" style="min-width:9rem;">
            {times[selected].tz_convert(timezone):%Y-%m-%d %H:%M}</strong>
    </div>
    """
    minutes = int(step.total_seconds() // 60)
    blurb = (
        f"{len(times)} frames, one every {minutes} min, each wire's last {label.lower()} "
        f"at or before that moment. One colour scale for the whole window. Greyed boxes "
        f"hold a reading older than {int(stale.total_seconds() // 60)} min; they are shown "
        "but not used in the colours."
    )
    return render_card(
        f"{html.escape(label)} side section replay",
        controls + svg + REPLAY_JS,
        description=blurb, card_class="card",
    )


@router.get("/multi_height/side-section", response_class=HTMLResponse)
async def side_section_page(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    measurement: Annotated[str, Query(description="par, temp, hum or co2")] = (
        DEFAULT_SECTION_MEASUREMENT
    ),
    from_: Annotated[
        str | None,
        Query(alias="from", description="Replay window start (local time); omit for latest"),
    ] = None,
    to: Annotated[
        str | None, Query(description="Replay window end (local time); defaults to latest")
    ] = None,
    at: Annotated[
        str | None, Query(description="Frame to open on (local time), for linking")
    ] = None,
):
    """Latest values on every wire as a side section, or a replay of a window."""
    if measurement not in WIRE_SENSOR_MEASUREMENTS:
        measurement = DEFAULT_SECTION_MEASUREMENT
    timezone = deps.base_settings.display_timezone
    label, unit = WIRE_MEASUREMENT_LABELS[measurement]

    window = None
    start = _parse_local_instant(from_, timezone)
    if start is not None:
        wires = await wire_ids()
        latest = await latest_reading_time(wires)
        window = resolve_window(
            start, _parse_local_instant(to, timezone),
            None if latest is None else latest.to_pydatetime(),
        )

    if window is not None:
        extra = {
            "from": _local_input(window[0], timezone),
            "to": _local_input(window[1], timezone),
        }
        form = _replay_form(window[0], window[1], measurement, timezone)
        card = await _replay_card(
            window, _parse_local_instant(at, timezone), measurement, wires, timezone,
        )
    else:
        extra = {}
        form = _replay_form_empty(measurement)
        nodes, layout, timezone = await _latest_section_nodes(measurement)
        card = _section_card(
            nodes, timezone, label, "side section",
            lambda: render_side_svg(nodes, layout, measurement, label, unit),
            f"Each column is one wire with its latest {label.lower()}, H1 at the top "
            "to H5 at the bottom. The colour between wires and heights is interpolated.",
        )
    measurement_pills = _section_measurement_pills(
        "/multi_height/side-section", measurement, extra,
    )

    content = f"""
    <a href="/multi_height" class="back-link">← Multi Height</a>
    <h1>Side Section of Wires</h1>

    <div style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center;">
        {measurement_pills}
    </div>
    {form}

    {card}
    """

    return render_page(config.title, content)


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

    wires = await wire_ids()
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

    df = await load_wire_readings(start_utc, end_utc)
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


def _date_form(base_path: str, day: date, wire: str | None, extra=None) -> str:
    """Single-date picker that GETs back to this view, keeping its selection.

    The picker is a form while the other selectors are pill links, so whatever
    those selected has to ride along as hidden inputs or submitting the date
    would silently reset them.
    """
    carried = {"wire": wire, **(extra or {})}
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{html.escape(str(value))}">'
        for name, value in carried.items()
        if value
    )
    return f"""
    <form method="get" action="{base_path}" style="display:flex;gap:12px;
        align-items:flex-end;margin-bottom:16px;flex-wrap:wrap;">
        {hidden}
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

    wires = await wire_ids()
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
    Click any cell to expand its chart.
    <a href="/multi_height/uniformity?date={table_date}">Compare wires →</a>
    <a href="/climate/forecast?wire={wire}">What is coming →</a></p>

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
    if wire not in await wire_ids():
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
    if wire not in await wire_ids():
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


### Uniformity across wires ###
# No ``wire`` param on purpose: this page exists to compare them, and making the
# reader pick one would hide the comparison (the reversal ``crop_cycles`` already
# recorded). Growth sections map onto the same heights on every wire, which is
# what makes the columns comparable at all — see CONTEXT "Growth section".
@router.get("/multi_height/uniformity", response_class=HTMLResponse)
async def uniformity_page(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    day: Annotated[
        date | None,
        Query(alias="date", description="Day to view (YYYY-MM-DD); defaults to latest with data"),
    ] = None,
    metric: Annotated[
        str,
        Query(description="Metric to compare (par/temp/hum/co2/dli/vpd/fungal)"),
    ] = DEFAULT_UNIFORMITY_METRIC,
):
    if metric not in CROP_METRICS:
        metric = DEFAULT_UNIFORMITY_METRIC

    timezone = deps.base_settings.display_timezone
    wires = await wire_ids()
    risk_t = load_risk_thresholds(deps._METADATA_PATH)
    # Read per request beside the risk thresholds, not cached at import: both are
    # PROVISIONAL, and retuning either is meant to stay a YAML edit rather than a
    # redeploy.
    uniformity_cfg = load_uniformity_config(deps._METADATA_PATH)

    # Default to the latest day any wire reported, so a lagging feed never opens
    # on an empty page. One cheap aggregate covers every wire, not one each.
    target_date = day or await latest_reporting_date(wires, timezone)

    # One fetch covers every wire: the readings query is not scoped by device, so
    # the comparison costs the same as the single-wire page it sits beside.
    fetch_start, fetch_end = day_window_utc(
        target_date or date.today(), timezone, risk_t.fungal.window_hours,
    )
    df = await load_wire_readings(fetch_start, fetch_end)

    view = build_uniformity_day(
        df, wires, deps.growth_sections, risk_t, uniformity_cfg,
        metric, timezone, target_date=target_date,
    )
    table_date = view.day_start.date().isoformat()
    label, unit = METRIC_LABELS[metric]

    metric_pills = pill_row(
        "/multi_height/uniformity", "metric",
        [(m, METRIC_LABELS[m][0]) for m in CROP_METRICS], metric,
        {"date": day.isoformat() if day else None}, label="Metric",
    )
    date_form = _date_form(
        "/multi_height/uniformity", view.day_start.date(), None,
        extra={"metric": metric},
    )

    worst = view.worst_spread
    if worst is None:
        headline = (
            "Not enough wires reported this day to compare — "
            "every column stands alone."
        )
    else:
        headline = (
            f"Widest disagreement today: <b>{worst:.2f} {unit}</b> "
            f"({len(view.comparable_wires)} of {len(wires)} wires compared, "
            f"against a notable spread of {view.notable_spread:g} {unit})."
        )

    profile = wire_profile_chart(view, timezone)
    profile_card = render_card(
        f"Profile — {table_date}",
        profile or '<p style="color:#6b7280;margin:0;">Nothing measured today.</p>',
        description="The same reading against height. Wires that differ by a "
        "constant draw parallel lines; one reading a different microclimate at "
        "a single section draws a kink there. Dashed = not compared.",
        card_class="card",
    )

    content = f"""
    <a href="/multi_height" class="back-link">← Multi Height</a>
    <h1>Uniformity across Wires</h1>
    <p>Every declared wire's growth sections side by side. The bold number is
    what the wires are compared on — {aggregate_phrase(metric)} — with the
    latest reading under it. Only the Spread column is coloured, and on an
    absolute scale, so it means the same thing on every metric and every day; a
    wire that reported too little is greyed and left out of the comparison.</p>

    <div style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center;">
        {metric_pills}
    </div>
    {date_form}

    {render_card(
        f"{label} by wire — {table_date}",
        uniformity_table(view) + spread_legend(view),
        description=headline,
        card_class="card",
    )}

    {profile_card}

    {render_card(
        "Verdict",
        verdict_list(view, uniformity_cfg.min_coverage_hours),
        description="A wire that drifts the same way at every height is placed "
        "or calibrated differently; one that disagrees at a single height is "
        "reading a genuinely different microclimate there.",
        card_class="card",
    )}
    """

    return render_page(config.title, content)


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
    wires = await wire_ids()
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
    if metric not in CROP_METRICS or height not in WIRE_SENSOR_HEIGHTS:
        return HTMLResponse(
            '<p style="font:14px sans-serif;padding:1rem;color:#b91c1c;">'
            "Unknown chart.</p>",
            status_code=400,
        )

    wires = await wire_ids()
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
