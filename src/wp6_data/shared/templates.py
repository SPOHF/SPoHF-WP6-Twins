"""Shared HTML templates for WP6 dashboards."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wp6_data.shared.metadata import MetadataRegistry
    from wp6_data.shared.twin import DataSource, ThemeColors

_dashboard_id = "blue"
_dashboard_title = "SPoHF"
_twin_theme_css = ""
_data_sources: list[DataSource] = []
_current_user: ContextVar[str | None] = ContextVar("_current_user", default=None)


def _generate_twin_css(twin_id: str, theme: ThemeColors) -> str:
    """Generate CSS custom properties for one twin's colour palette."""
    return f"""
    [data-dashboard="{twin_id}"] {{
        --dashboard-primary: {theme.primary};
        --dashboard-primary-light: {theme.primary_light};
        --dashboard-primary-dark: {theme.primary_dark};
        --dashboard-accent: {theme.accent};
        --dashboard-gradient-start: {theme.primary};
        --dashboard-gradient-end: {theme.accent};
        --dashboard-surface: rgba({theme.surface_rgb}, 0.04);
        --dashboard-surface-hover: rgba({theme.surface_rgb}, 0.08);
    }}
    [data-theme="dark"][data-dashboard="{twin_id}"] {{
        --dashboard-surface: rgba({theme.surface_rgb}, 0.08);
        --dashboard-surface-hover: rgba({theme.surface_rgb}, 0.14);
    }}"""


def configure_dashboard(
    dashboard_id: str,
    *,
    title: str = "SPoHF",
    theme: ThemeColors | None = None,
    data_sources: list[DataSource] | None = None,
) -> None:
    """Set the dashboard identity and theme. Call once at startup."""
    global _dashboard_id, _dashboard_title, _twin_theme_css, _data_sources
    _dashboard_id = dashboard_id
    _dashboard_title = title
    _data_sources = data_sources or []
    if theme is not None:
        _twin_theme_css = _generate_twin_css(dashboard_id, theme)


def utc_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """Return inclusive UTC start/end datetimes for a calendar date."""
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def default_date_range() -> tuple[date, date]:
    """Return default date range: last 7 days."""
    end = date.today()
    start = end - timedelta(days=7)
    return start, end


def resolve_date_range(
    start: date | None = None,
    end: date | None = None,
) -> tuple[date, date, datetime, datetime]:
    """Apply defaults and convert date params to a (date, date, datetime, datetime) tuple."""
    default_start, default_end = default_date_range()
    start = start or default_start
    end = end or default_end
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)
    return start, end, start_dt, end_dt


def render_date_filter(start: date, end: date, extra_params: dict[str, str] | None = None) -> str:
    """Render an HTML date-range filter with quick-select presets and custom inputs."""
    today = date.today()
    presets = [
        ("1d", 1),
        ("7d", 7),
        ("30d", 30),
        ("90d", 90),
        ("1y", 365),
        ("All", None),
    ]
    # Determine which preset is active
    active = None
    for label, days in presets:
        if days is None:
            if start == date(2024, 1, 1) and end == today:
                active = label
        elif start == today - timedelta(days=days) and end == today:
            active = label

    buttons = []
    for label, days in presets:
        cls = "contrast" if label == active else "outline"
        js_days = "null" if days is None else str(days)
        buttons.append(
            f'<button type="button" class="{cls}" onclick="setRange({js_days})">'
            f"{label}</button>"
        )

    hidden_fields = ""
    if extra_params:
        hidden_fields = "".join(
            f'<input type="hidden" name="{k}" value="{v}">' for k, v in extra_params.items()
        )

    return f"""
    <article class="date-filter">
    <form id="dateFilter" method="get">
        {hidden_fields}
        <div class="date-presets">
            {''.join(buttons)}
        </div>
        <div class="date-inputs">
            <input type="date" id="df-start" name="start"
                   value="{start.isoformat()}" title="From"
                   onchange="document.getElementById('dateFilter').submit()">
            <span class="date-sep">&ndash;</span>
            <input type="date" id="df-end" name="end"
                   value="{end.isoformat()}" title="To"
                   onchange="document.getElementById('dateFilter').submit()">
        </div>
    </form>
    </article>
    <script>
    function setRange(days) {{
        var end = new Date();
        var start = days === null
            ? new Date('2024-01-01')
            : new Date(end.getTime() - days * 86400000);
        document.getElementById('df-start').value = start.toISOString().slice(0, 10);
        document.getElementById('df-end').value = end.toISOString().slice(0, 10);
        document.getElementById('dateFilter').submit();
    }}
    </script>
    """


def render_card(
    title: str, body: str, *, description: str = "", card_class: str = "",
) -> str:
    """Render content wrapped in a styled article card."""
    desc = f"<p>{description}</p>" if description else ""
    cls = f' class="{card_class}"' if card_class else ""
    return f"<article{cls}><h2>{title}</h2>{desc}{body}</article>"


def render_table(headers: list[str], rows: list[list[str]], *, sortable: bool = True) -> str:
    """Render an HTML table from headers and row data (cells may contain HTML)."""
    thead = "<tr>" + "".join(
        f'<th style="cursor:pointer" onclick="sortTable(this)">{h}</th>'
        if sortable else f"<th>{h}</th>"
        for h in headers
    ) + "</tr>"
    tbody = "".join(
        "<tr>" + "".join(
            f'<td data-sort="{cell[1]}">{cell[0]}</td>'
            if isinstance(cell, tuple)
            else f"<td>{cell}</td>"
            for cell in row
        ) + "</tr>"
        for row in rows
    )
    return f"<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>"


def build_home_tables(
    metadata: MetadataRegistry,
    devices: dict[str, dict],
    available_exports: dict[str, str],
) -> tuple[str, str]:
    """Build the sensor-type and device tables for a home page.

    Args:
        metadata: The twin's metadata registry.
        devices: ``{device_id: {"sensors": [str], "readings": int}}``.
        available_exports: Export availability dict for download links.

    Returns:
        ``(sensor_table_html, device_table_html)``
    """
    from wp6_data.shared.export import render_download_link

    # --- Sensor type table ---
    # Aggregate per-sensor: total readings + set of devices
    sensor_readings: dict[str, int] = {}
    sensor_devices: dict[str, set[str]] = {}
    for device_id, info in devices.items():
        for s in info["sensors"]:
            sensor_readings[s] = sensor_readings.get(s, 0) + info["readings"]
            sensor_devices.setdefault(s, set()).add(device_id)

    sensor_entries = []
    for key in sorted(sensor_readings, key=lambda k: -sensor_readings[k]):
        sm = metadata.sensor_default(key)
        sensor_entries.append({
            "key": key,
            "url": chart_url([
                f"{d}:{key}" for d in sorted(sensor_devices.get(key, set()))
            ]),
            "type": sm.type,
            "alias": sm.alias,
            "unit": sm.unit,
            "Devices": ", ".join(sorted(sensor_devices.get(key, set()))),
            "Readings": f"{sensor_readings[key]:,}",
        })
    sensor_table = render_sensor_type_table(
        sensor_entries, extra_headers=["Devices", "Readings"],
    )

    # --- Device table ---
    # Pre-build position and device-type series for group links
    position_series: dict[str, list[str]] = {}
    dtype_series: dict[str, list[str]] = {}
    for device_id, info in devices.items():
        dm = metadata.device(device_id)
        series = [f"{device_id}:{s}" for s in sorted(info["sensors"])]
        if dm.position:
            position_series.setdefault(dm.position, []).extend(series)
        if dm.type:
            dtype_series.setdefault(dm.type, []).extend(series)

    device_entries = []
    for device_id, info in sorted(devices.items()):
        dm = metadata.device(device_id)
        dev_series = [f"{device_id}:{s}" for s in sorted(info["sensors"])]
        sensor_links = ", ".join(
            f'<a href="{chart_url([f"{device_id}:{s}"])}">'
            f"{metadata.sensor_default(s).alias or s}</a>"
            for s in sorted(info["sensors"])
        )
        pos_html = (
            f'<a href="{chart_url(position_series[dm.position])}">'
            f"{dm.position}</a>"
            if dm.position
            else ""
        )
        type_html = (
            f'<a href="{chart_url(dtype_series[dm.type])}">'
            f"{dm.type}</a>"
            if dm.type
            else ""
        )
        device_entries.append({
            "name": f'<a href="{chart_url(dev_series)}">{device_id}</a>',
            "position": pos_html,
            "type": type_html,
            "sensors": sensor_links,
            "readings": f'{info["readings"]:,}' if info["readings"] else "",
            "Download": render_download_link(device_id, available_exports),
        })
    device_table = render_device_table(
        device_entries, extra_columns=["Download"],
    )

    return sensor_table, device_table


def chart_url(series: list[str]) -> str:
    """Build a /chart?s=... URL from a list of device:sensor keys."""
    from urllib.parse import urlencode

    if not series:
        return "/chart"
    return f"/chart?{urlencode({'s': ','.join(series)})}"


def render_sensor_type_table(
    sensors: list[dict[str, str]],
    *,
    extra_headers: list[str] | None = None,
) -> str:
    """Render a sensor table grouped by sensor type.

    Each dict in *sensors* should have keys:
        - ``key``: sensor/measurement key (used as fallback label)
        - ``url``: link target for the sensor name
        - ``type``: sensor type for grouping (rows without type are skipped)
        - ``alias``: display name (falls back to key)
        - ``unit``: unit of measurement
    Plus any extra keys matching *extra_headers*.
    """
    from collections import defaultdict as _defaultdict

    type_groups: dict[str, list[dict[str, str]]] = _defaultdict(list)
    for s in sensors:
        if s.get("type"):
            type_groups[s["type"]].append(s)

    headers = ["Type", "Sensor", "Unit"]
    if extra_headers:
        headers.extend(extra_headers)

    rows: list[list] = []
    for sensor_type in sorted(type_groups):
        items = type_groups[sensor_type]
        for i, s in enumerate(items):
            type_html = (
                f'<strong><a href="/type/{sensor_type}">'
                f"{sensor_type}</a></strong>"
                if i == 0
                else ""
            )
            # Tuple (html, sort_value) so empty cells still sort correctly
            type_cell = (type_html, sensor_type)
            row: list = [
                type_cell,
                f'<a href="{s["url"]}">{s.get("alias") or s["key"]}</a>',
                s.get("unit", ""),
            ]
            if extra_headers:
                for h in extra_headers:
                    row.append(s.get(h, ""))
            rows.append(row)

    return render_table(headers, rows)


def render_device_table(
    devices: list[dict[str, str]],
    *,
    extra_columns: list[str] | None = None,
) -> str:
    """Render a uniform device table from metadata-enriched entries.

    Each dict in *devices* should have keys:
        - ``name``: device name/id (displayed as-is, may contain HTML links)
        - ``position``: from device metadata
        - ``type``: from device metadata
        - ``sensors``: comma-separated sensor aliases
        - ``readings``: formatted reading count
    Plus any extra keys matching *extra_columns* headers.
    """
    headers = ["Device", "Position", "Type", "Sensors", "Readings"]
    if extra_columns:
        headers.extend(extra_columns)

    rows: list[list[str]] = []
    for d in devices:
        row = [
            d.get("name", ""),
            d.get("position", ""),
            d.get("type", ""),
            d.get("sensors", ""),
            d.get("readings", ""),
        ]
        if extra_columns:
            for col in extra_columns:
                row.append(d.get(col, ""))
        rows.append(row)

    return render_table(headers, rows)


BASE_CSS = """
    :root {
        --pico-font-size: 93.75%;
        --pico-block-spacing-vertical: 0.5rem;
        --pico-block-spacing-horizontal: 0.5rem;
        --pico-form-element-spacing-vertical: 0.4rem;
        --pico-form-element-spacing-horizontal: 0.6rem;
        --pico-typography-spacing-vertical: 0.75rem;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
                     Ubuntu, Cantarell, "Helvetica Neue", Arial, sans-serif;
    }

    /* Twin-specific theme CSS is generated by configure_dashboard() */
    /* Map Pico vars to dashboard vars — :root bumps specificity to (0,2,0)
       to beat Pico's :root:not([data-theme=dark]) */
    :root[data-dashboard] {
        --pico-primary: var(--dashboard-primary);
        --pico-primary-hover: var(--dashboard-primary-dark);
        --pico-primary-background: var(--dashboard-primary);
        --pico-primary-hover-background: var(--dashboard-primary-dark);
        --pico-primary-border: var(--dashboard-primary);
        --pico-primary-hover-border: var(--dashboard-primary-dark);
        --pico-primary-focus: var(--dashboard-primary-light);
        --pico-primary-underline: var(--dashboard-primary-light);
        --pico-primary-inverse: #fff;
    }
    /* Dark mode — lighter hover for contrast on dark bg */
    [data-theme="dark"][data-dashboard] {
        --pico-primary: var(--dashboard-primary-light);
        --pico-primary-hover: var(--dashboard-primary);
        --pico-primary-background: var(--dashboard-primary);
        --pico-primary-hover-background: var(--dashboard-primary-dark);
        --pico-primary-border: var(--dashboard-primary-light);
        --pico-primary-hover-border: var(--dashboard-primary);
        --pico-primary-focus: var(--dashboard-primary-light);
        --pico-primary-underline: var(--dashboard-primary-light);
        --pico-primary-inverse: #fff;
    }
    /* --- Typography --- */
    h1, h2, h3 { letter-spacing: -0.01em; }
    h1 { --pico-typography-spacing-vertical: 1rem; }

    /* --- Nav bar --- */
    .dashboard-nav {
        position: sticky; top: 0; z-index: 100;
        display: flex; align-items: center; justify-content: space-between;
        padding: 0.6rem 1.2rem;
        border-bottom: 2px solid var(--dashboard-primary);
        background: var(--pico-background-color);
        backdrop-filter: blur(8px);
    }
    .dashboard-nav .brand {
        font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em;
        background: linear-gradient(135deg, var(--dashboard-gradient-start),
                                             var(--dashboard-gradient-end));
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text; color: transparent;
    }
    .dashboard-nav .nav-links { display: flex; align-items: center; gap: 1rem; }
    .dashboard-nav .nav-links a {
        font-size: 0.85rem; text-decoration: none; opacity: 0.7;
    }
    .dashboard-nav .nav-links a:hover { opacity: 1; }
    .nav-user { font-size: 0.8rem; opacity: 0.6; white-space: nowrap; }
    #theme-toggle {
        background: var(--dashboard-surface);
        border: 1.5px solid var(--dashboard-primary);
        border-radius: 8px; padding: 0.3rem 0.55rem; cursor: pointer;
        font-size: 1rem; line-height: 1;
        color: var(--dashboard-primary);
    }
    #theme-toggle:hover {
        background: var(--dashboard-surface-hover);
    }
    /* Show correct icon per theme */
    .icon-sun { display: none; }
    .icon-moon { display: inline; }
    [data-theme="dark"] .icon-sun { display: inline; }
    [data-theme="dark"] .icon-moon { display: none; }

    /* --- Cards / articles --- */
    article {
        position: relative; overflow: hidden;
        padding: 1rem; border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    article:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1), 0 2px 4px rgba(0,0,0,0.06);
    }
    [data-theme="dark"] article:hover {
        box-shadow: 0 4px 12px rgba(255,255,255,0.08), 0 2px 4px rgba(255,255,255,0.05);
    }
    .card-primary { border: 2px solid var(--pico-primary-background); }

    /* Card background illustrations */
    .card-bg::after {
        content: ''; position: absolute;
        top: -10%; bottom: -10%; left: 0; right: -3%;
        pointer-events: none; z-index: 0;
        background-size: auto 100%;
        background-position: center right;
        background-repeat: no-repeat;
        -webkit-mask-image: linear-gradient(to right,
            transparent 15%, black 65%);
        mask-image: linear-gradient(to right,
            transparent 15%, black 65%);
    }
    .card-bg > * { position: relative; z-index: 1; }
    html:not([data-theme="dark"]) .card-bg::after {
        filter: invert(1);
    }
    .card-bg-chart::after {
        background-image: url(/static/cards/line_chart.svg);
    }
    .card-bg-sun::after {
        background-image: url(/static/cards/sun.svg);
    }
    .card-bg-status::after {
        background-image: url(/static/cards/status.svg);
    }

    /* --- Stats cards --- */
    .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
    .stats-grid.cols-4 { grid-template-columns: repeat(4, 1fr); }
    .stats-grid.cols-5 { grid-template-columns: repeat(5, 1fr); }
    .stats-grid.cols-auto { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
    .stats-grid article {
        text-align: center; margin-bottom: 0;
        background: linear-gradient(135deg, var(--dashboard-gradient-start),
                                             var(--dashboard-gradient-end));
        color: #fff; border: none;
    }
    .stats-grid article small { color: rgba(255,255,255,0.85); }
    .stat-value { font-size: 1.6em; font-weight: 800; color: #fff; }
    .success { color: #16a34a !important; }
    .warning { color: #f59e0b !important; }
    [data-theme="dark"] .success { color: #4ade80 !important; }
    [data-theme="dark"] .warning { color: #fbbf24 !important; }

    /* --- Date filter --- */
    .date-filter {
        padding: 0.75rem 1rem;
        border-left: 3px solid var(--dashboard-primary);
        background: var(--dashboard-surface);
        border-radius: 0 12px 12px 0;
    }
    .date-filter form { margin-bottom: 0; }
    .date-presets { display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
    .date-presets button { width: auto; padding: 0.25rem 0.75rem; margin-bottom: 0; }
    .date-presets button:hover { transform: translateY(-1px); }
    .date-inputs { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .date-inputs label { margin-bottom: 0; }
    .date-inputs button { width: auto; padding: 0.25rem 0.75rem; margin-bottom: 0; }

    /* --- Tables --- */
    :root[data-dashboard] thead {
        background: transparent;
    }
    :root[data-dashboard] thead th {
        background: transparent;
        color: var(--dashboard-primary);
        --pico-color: var(--dashboard-primary);
        border-bottom: 2px solid var(--dashboard-primary);
        user-select: none;
        font-weight: 700;
    }
    thead th[onclick]:hover { opacity: 0.8; }
    tbody tr { transition: background 0.1s ease; }
    tbody tr:hover { background: var(--dashboard-surface-hover); }

    /* --- Buttons --- */
    button, [type="submit"] { transition: transform 0.1s ease; }
    button:hover, [type="submit"]:hover { transform: translateY(-1px); }

    /* --- Back link & logo --- */
    .back { margin-bottom: 20px; }
    .logo { margin-bottom: 20px; }
    .logo img { max-height: 80px; }

    /* --- Footer --- */
    footer {
        margin-top: 40px; padding-top: 20px;
        border-top: 1px solid var(--pico-muted-border-color);
    }
    .footer-logo { max-height: 60px; transition: opacity 0.15s ease; }
    .footer-logo:hover { opacity: 0.7; }

    /* --- Collapsible date filter --- */
    .date-filter-collapsible {
        padding: 0;
        margin-bottom: 0.5rem;
        border: none;
        box-shadow: none;
    }
    .date-filter-collapsible summary {
        cursor: pointer;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--dashboard-primary);
        padding: 0.4rem 0.75rem;
        border-left: 3px solid var(--dashboard-primary);
        background: var(--dashboard-surface);
        border-radius: 0 8px 8px 0;
    }
    .date-filter-collapsible[open] summary {
        margin-bottom: 0;
        border-radius: 0 8px 0 0;
    }
    .date-filter-collapsible .date-filter {
        border-radius: 0 0 12px 0;
        margin-bottom: 0;
        padding: 0.4rem 0.5rem;
    }
    .sensor-panel .date-filter-collapsible {
        margin-bottom: 0.5rem;
    }
    .sensor-panel .date-presets {
        flex-wrap: wrap;
        gap: 2px;
    }
    .sensor-panel .date-presets button {
        padding: 0.15rem 0.5rem;
        font-size: 0.75rem;
    }
    .sensor-panel .date-inputs {
        display: flex;
        align-items: center;
        gap: 2px;
    }
    .sensor-panel .date-inputs input[type="date"] {
        font-size: 0.72rem;
        padding: 0.15rem 0.25rem;
        flex: 1;
        min-width: 0;
    }
    .sensor-panel .date-sep {
        font-size: 0.75rem;
        opacity: 0.5;
        flex-shrink: 0;
    }
    .date-filter-collapsible:hover {
        transform: none;
        box-shadow: none;
    }

    /* --- Unified chart layout --- */
    .chart-layout {
        display: flex;
        gap: 0;
        min-height: 600px;
    }
    .sensor-panel {
        width: 260px;
        min-width: 260px;
        border-right: 2px solid var(--dashboard-primary);
        padding: 0.75rem;
        overflow-y: auto;
        max-height: 80vh;
        background: var(--dashboard-surface);
        transition: width 0.2s, min-width 0.2s, padding 0.2s;
    }
    .sensor-panel.collapsed {
        width: 0;
        min-width: 0;
        padding: 0;
        overflow: hidden;
        border-right: none;
    }
    .sensor-panel h4 {
        margin: 0 0 0.5rem 0;
        font-size: 0.9rem;
        color: var(--dashboard-primary);
    }
    .chart-main {
        flex: 1;
        min-width: 0;
        padding: 0 0.5rem;
    }
    .panel-toggle {
        font-size: 0.8rem;
        padding: 0.2rem 0.6rem;
        margin-bottom: 0.5rem;
        cursor: pointer;
        width: auto;
    }

    /* Measurement groups in side panel */
    .sensor-group {
        margin-bottom: 0.5rem;
    }
    .sensor-group summary {
        font-size: 0.82rem;
        font-weight: 600;
        cursor: pointer;
        padding: 0.15rem 0;
        color: var(--dashboard-primary);
    }
    .sensor-item {
        display: flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.1rem 0 0.1rem 0.5rem;
        font-size: 0.78rem;
    }
    .sensor-item .cb-label {
        margin: 0;
        padding: 0;
        font-size: 0.7rem;
        font-weight: 600;
        opacity: 0.6;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 1px;
    }
    .sensor-item .cb-label:has(:checked) {
        opacity: 1;
        color: var(--dashboard-primary);
    }
    .sensor-item input[type="checkbox"] {
        margin: 0;
        transform: scale(0.8);
    }
    .sensor-item .device-name {
        font-size: 0.78rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
    }
    .sensor-item .device-name:hover {
        color: var(--dashboard-primary);
    }
    .group-badge {
        font-size: 0.7rem;
        font-weight: 700;
        color: var(--dashboard-primary);
    }
    .sensor-panel h4 {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .clear-btn {
        font-size: 0.7rem;
        opacity: 0.5;
        text-decoration: none;
        font-weight: 400;
    }
    .clear-btn:hover {
        opacity: 1;
    }
    .group-toggle {
        display: flex;
        margin-bottom: 0.5rem;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid var(--dashboard-primary);
    }
    .group-btn {
        flex: 1;
        font-size: 0.72rem;
        padding: 0.25rem 0.3rem;
        margin-bottom: 0;
        cursor: pointer;
        border: none;
        border-radius: 0;
        background: transparent;
        color: var(--dashboard-primary);
        transition: background 0.15s, color 0.15s;
    }
    .group-btn:not(:last-child) {
        border-right: 1px solid var(--dashboard-primary);
    }
    .group-btn.active {
        background: var(--dashboard-primary);
        color: #fff;
    }
    .group-btn:not(.active):hover {
        background: color-mix(in srgb, var(--dashboard-primary) 12%, transparent);
    }
    .unit-badge {
        font-size: 0.65rem;
        opacity: 0.5;
        margin-left: 2px;
    }
    .sensor-item.active {
        background: var(--dashboard-surface-hover);
        border-radius: 4px;
    }
    #chart-area {
        min-height: 500px;
    }
    .chart-stats {
        font-size: 0.82rem;
        opacity: 0.7;
        margin: 0.25rem 0;
    }
    .truncation-warning {
        color: #f59e0b;
        font-weight: 600;
    }
    [data-theme="dark"] .truncation-warning {
        color: #fbbf24;
    }
    .chart-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 400px;
        opacity: 0.5;
        font-size: 1.1rem;
    }

    /* --- Charts: dark mode invert --- */
    [data-theme="dark"] .js-plotly-plot {
        filter: invert(0.88) hue-rotate(180deg);
    }
"""


THEME_JS = """
    (function() {
        var t = localStorage.getItem('wp6-theme') || 'light';
        document.documentElement.dataset.theme = t;
    })();
"""

TOGGLE_JS = """
    document.getElementById('theme-toggle').addEventListener('click', function() {
        var html = document.documentElement;
        var next = html.dataset.theme === 'dark' ? 'light' : 'dark';
        html.dataset.theme = next;
        localStorage.setItem('wp6-theme', next);
    });
"""

TABLE_SORT_JS = """
    function sortTable(th) {
        var table = th.closest('table');
        var tbody = table.querySelector('tbody');
        var idx = Array.from(th.parentNode.children).indexOf(th);
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var asc = th.dataset.sortDir !== 'asc';
        // Reset all headers
        th.parentNode.querySelectorAll('th').forEach(function(h) {
            h.dataset.sortDir = '';
            h.textContent = h.textContent.replace(/ [\\u25B2\\u25BC]$/, '');
        });
        th.dataset.sortDir = asc ? 'asc' : 'desc';
        th.textContent += asc ? ' \\u25B2' : ' \\u25BC';
        rows.sort(function(a, b) {
            var ac = a.children[idx], bc = b.children[idx];
            var at = ac.dataset.sort || ac.textContent.trim();
            var bt = bc.dataset.sort || bc.textContent.trim();
            // Try numeric comparison (strip commas for formatted numbers)
            var an = parseFloat(at.replace(/,/g, ''));
            var bn = parseFloat(bt.replace(/,/g, ''));
            if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
            return asc ? at.localeCompare(bt) : bt.localeCompare(at);
        });
        rows.forEach(function(r) { tbody.appendChild(r); });
    }
"""

UNIFIED_CHART_JS = """
(function() {
    var chartDiv = document.getElementById('chart-area');
    var panelDiv = document.getElementById('sensor-panel');
    var statsDiv = document.getElementById('chart-stats');
    var toggleBtn = document.getElementById('panel-toggle');
    if (!chartDiv || !panelDiv) return;

    // State: map of "device:sensor" -> {axis: "left"|"right", traceIdx: number}
    var activeSeries = {};
    var totalPoints = 0;

    // Parse URL params
    var params = new URLSearchParams(window.location.search);
    var leftSpecs = (params.get('s') || '').split(',').filter(Boolean);
    var rightSpecs = (params.get('r') || '').split(',').filter(Boolean);
    var startDate = params.get('start') || '';
    var endDate = params.get('end') || '';

    // Build initial active set from URL
    var initialLeft = {};
    var initialRight = {};
    leftSpecs.forEach(function(s) { initialLeft[s] = true; });
    rightSpecs.forEach(function(s) { initialRight[s] = true; });

    // Initialize empty Plotly chart
    var layout = {
        template: 'plotly_white',
        hovermode: 'x unified',
        height: 600,
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        yaxis2: {overlaying: 'y', side: 'right', showgrid: false}
    };
    Plotly.newPlot(chartDiv, [], layout);

    // Toggle panel
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            var sp = document.querySelector('.sensor-panel');
            sp.classList.toggle('collapsed');
            toggleBtn.textContent = sp.classList.contains('collapsed')
                ? 'Show controls' : 'Hide controls';
            Plotly.Plots.resize(chartDiv);
        });
    }

    // Clear all selections
    var clearBtn = document.getElementById('clear-all');
    if (clearBtn) {
        clearBtn.addEventListener('click', function(e) {
            e.preventDefault();
            // Remove all traces from chart
            var keys = Object.keys(activeSeries);
            if (keys.length === 0) return;
            var indices = keys.map(function(k) {
                return activeSeries[k].traceIdx;
            }).sort(function(a, b) { return b - a; });
            Plotly.deleteTraces(chartDiv, indices);
            activeSeries = {};
            totalPoints = 0;
            // Uncheck all checkboxes
            var cbs = panelDiv.querySelectorAll(
                'input[type="checkbox"]:checked');
            cbs.forEach(function(cb) { cb.checked = false; });
            panelDiv.querySelectorAll('.sensor-item').forEach(
                function(el) { el.classList.remove('active'); });
            showEmpty(true);
            syncUrl();
            updateStats();
            updateY2();
            updateAllBadges();
        });
    }

    // Fetch sensor list (nested by device) and flatten for internal use
    var allSensors = [];
    var currentGrouping = 'measurement';
    fetch('/api/sensors')
        .then(function(r) { return r.json(); })
        .then(function(nested) {
            allSensors = [];
            nested.forEach(function(d) {
                var dm = d.meta || {};
                d.sensors.forEach(function(s) {
                    allSensors.push({
                        device: d.device,
                        sensor: s.sensor,
                        device_meta: dm,
                        sensor_meta: s.meta || {}
                    });
                });
            });
            buildTree(allSensors, currentGrouping);
            loadInitialSeries();
        });

    // Grouping toggle
    var groupBtns = document.querySelectorAll('.group-btn');
    groupBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var mode = btn.dataset.group;
            if (mode === currentGrouping) return;
            currentGrouping = mode;
            groupBtns.forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
            buildTree(allSensors, currentGrouping);
        });
    });

    function buildTree(sensors, groupBy) {
        // Group sensors into {groupKey: [{device, sensor, ...}, ...]}
        var groups = {};
        sensors.forEach(function(s) {
            var key;
            if (groupBy === 'device') key = s.device;
            else if (groupBy === 'position')
                key = (s.device_meta && s.device_meta.position) || 'Ungrouped';
            else key = (s.sensor_meta && s.sensor_meta.type) || s.sensor;
            if (!groups[key]) groups[key] = [];
            groups[key].push(s);
        });

        // Build current checked state from activeSeries
        var checkedLeft = {};
        var checkedRight = {};
        Object.keys(activeSeries).forEach(function(k) {
            if (activeSeries[k].axis === 'right') checkedRight[k] = true;
            else checkedLeft[k] = true;
        });
        // On first load, also use URL state
        if (Object.keys(activeSeries).length === 0) {
            checkedLeft = initialLeft;
            checkedRight = initialRight;
        }

        var html = '';
        var sortedKeys = Object.keys(groups).sort();
        sortedKeys.forEach(function(groupKey) {
            var items = groups[groupKey];
            var open = items.some(function(s) {
                var key = s.device + ':' + s.sensor;
                return checkedLeft[key] || checkedRight[key];
            });
            html += '<details class="sensor-group"'
                + (open ? ' open' : '') + '>';
            html += '<summary>' + groupKey
                + ' <small>(' + items.length + ')</small>'
                + '<span class="group-badge"></span>'
                + '</summary>';
            items.forEach(function(s) {
                var key = s.device + ':' + s.sensor;
                var sm = s.sensor_meta || {};
                var dm = s.device_meta || {};
                // Display label: use alias if available
                var label;
                if (groupBy === 'device') label = sm.alias || s.sensor;
                else if (groupBy === 'position') label = (sm.alias || s.sensor) + ' — ' + s.device;
                else label = s.device + ' — ' + (sm.alias || s.sensor);
                // Unit badge
                var unitBadge = sm.unit
                    ? ' <span class="unit-badge">' + sm.unit + '</span>'
                    : '';
                // Tooltip with metadata
                var tipParts = [key];
                if (dm.description) tipParts.push(dm.description);
                if (dm.position) tipParts.push('Position: ' + dm.position);
                if (sm.intention) tipParts.push(sm.intention);
                if (dm.type) tipParts.push('Type: ' + dm.type);
                var tip = tipParts.join(' | ');
                var isLeft = !!checkedLeft[key];
                var isRight = !!checkedRight[key];
                var activeClass = (isLeft || isRight)
                    ? ' active' : '';
                html += '<div class="sensor-item' + activeClass
                    + '" data-key="' + key + '">';
                html += '<label class="cb-label" title="Left Y">'
                    + '<input type="checkbox" data-axis="left"'
                    + ' data-key="' + key + '"'
                    + (isLeft ? ' checked' : '')
                    + '> L</label>';
                html += '<label class="cb-label" title="Right Y">'
                    + '<input type="checkbox" data-axis="right"'
                    + ' data-key="' + key + '"'
                    + (isRight ? ' checked' : '')
                    + '> R</label>';
                html += '<span class="device-name" title="'
                    + tip + '">' + label + unitBadge + '</span>';
                html += '</div>';
            });
            html += '</details>';
        });
        panelDiv.innerHTML = html;
        updateAllBadges();
    }

    // Listen for changes (once, outside buildTree to avoid stacking)
    panelDiv.addEventListener('change', function(e) {
        var cb = e.target;
        if (cb.type !== 'checkbox') return;
        var key = cb.dataset.key;
        var axis = cb.dataset.axis;
        var otherAxis = axis === 'left' ? 'right' : 'left';
        var item = panelDiv.querySelector(
            '[data-key="' + key + '"]');

        if (cb.checked) {
            // Uncheck the other axis for this sensor
            var other = item.querySelector(
                'input[data-axis="' + otherAxis + '"]');
            if (other && other.checked) {
                other.checked = false;
            }
            addOrUpdateSeries(key, axis);
            if (item) item.classList.add('active');
        } else {
            removeSeries(key);
            // Check if any checkbox still checked
            var any = item.querySelector(
                'input[type="checkbox"]:checked');
            if (!any && item) {
                item.classList.remove('active');
            }
            // Sync immediately for removals (synchronous)
            syncUrl();
            updateStats();
            updateY2();
        }
        updateAllBadges();
    });

    // Clicking name toggles the L checkbox (once, outside buildTree)
    panelDiv.addEventListener('click', function(e) {
        var name = e.target.closest('.device-name');
        if (!name) return;
        var item = name.closest('.sensor-item');
        if (!item) return;
        var lcb = item.querySelector(
            'input[data-axis="left"]');
        if (lcb) {
            lcb.checked = !lcb.checked;
            lcb.dispatchEvent(
                new Event('change', {bubbles: true}));
        }
    });

    function updateAllBadges() {
        var groups = panelDiv.querySelectorAll('.sensor-group');
        groups.forEach(function(g) {
            var checked = g.querySelectorAll(
                'input[type="checkbox"]:checked');
            var badge = g.querySelector('.group-badge');
            if (badge) {
                badge.textContent = checked.length > 0
                    ? ' [' + checked.length + ']' : '';
            }
        });
    }

    function loadInitialSeries() {
        var allSpecs = leftSpecs.map(function(s) {
            return {key: s, axis: 'left'};
        }).concat(rightSpecs.map(function(s) {
            return {key: s, axis: 'right'};
        }));
        if (allSpecs.length === 0) {
            showEmpty(true);
            return;
        }
        showEmpty(false);
        var loaded = 0;
        allSpecs.forEach(function(spec) {
            fetchAndAdd(spec.key, spec.axis, function() {
                loaded++;
                if (loaded === allSpecs.length) {
                    updateStats();
                    updateY2();
                }
            });
        });
    }

    function sensorLabel(key) {
        var s = allSensors.find(function(s) {
            return s.device + ':' + s.sensor === key;
        });
        if (!s) return key;
        var alias = (s.sensor_meta && s.sensor_meta.alias) || s.sensor;
        return s.device + ' | ' + alias;
    }

    function fetchAndAdd(key, axis, cb) {
        var parts = key.split(':');
        var device = parts[0];
        var sensor = parts.slice(1).join(':');
        var url = '/api/series?device='
            + encodeURIComponent(device)
            + '&sensor=' + encodeURIComponent(sensor);
        if (startDate) url += '&start=' + startDate;
        if (endDate) url += '&end=' + endDate;

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                var data = resp.data || [];
                if (data.length === 0) { if (cb) cb(); return; }

                var times = data.map(function(d) {
                    return d.time;
                });
                var values = data.map(function(d) {
                    return d.value;
                });

                var trace = {
                    x: times,
                    y: values,
                    name: sensorLabel(key),
                    mode: 'lines',
                    yaxis: axis === 'right' ? 'y2' : 'y'
                };
                if (axis === 'right') {
                    trace.line = {dash: 'dash'};
                }

                Plotly.addTraces(chartDiv, [trace]);
                var idx = chartDiv.data.length - 1;
                activeSeries[key] = {
                    axis: axis, traceIdx: idx, points: data.length,
                    truncated: !!resp.truncated,
                    limit: resp.limit || 0
                };
                totalPoints += data.length;
                showEmpty(false);
                if (cb) cb();
            });
    }

    function addOrUpdateSeries(key, axis) {
        if (activeSeries[key]) {
            // Already loaded — just switch axis (synchronous)
            var idx = activeSeries[key].traceIdx;
            var yaxis = axis === 'right' ? 'y2' : 'y';
            var dash = axis === 'right' ? 'dash' : 'solid';
            Plotly.restyle(chartDiv, {
                yaxis: yaxis, 'line.dash': dash, visible: true
            }, [idx]);
            activeSeries[key].axis = axis;
            syncUrl();
            updateStats();
            updateY2();
        } else {
            // Need to fetch — syncUrl after fetch completes
            showEmpty(false);
            fetchAndAdd(key, axis, function() {
                syncUrl();
                updateStats();
                updateY2();
            });
        }
    }

    function removeSeries(key) {
        if (!activeSeries[key]) return;
        var idx = activeSeries[key].traceIdx;
        totalPoints -= activeSeries[key].points || 0;
        Plotly.deleteTraces(chartDiv, [idx]);
        delete activeSeries[key];
        // Reindex remaining traces
        Object.keys(activeSeries).forEach(function(k) {
            if (activeSeries[k].traceIdx > idx) {
                activeSeries[k].traceIdx--;
            }
        });
        if (Object.keys(activeSeries).length === 0) {
            showEmpty(true);
        }
    }

    function updateY2() {
        var hasY2 = chartDiv.data.some(function(t) {
            return t.visible !== false && t.yaxis === 'y2';
        });
        var relayoutUpdate = {
            'yaxis2.visible': hasY2,
            'yaxis2.showticklabels': hasY2
        };
        // Update axis labels based on units
        var leftUnits = {};
        var rightUnits = {};
        Object.keys(activeSeries).forEach(function(k) {
            var s = allSensors.find(function(s) {
                return s.device + ':' + s.sensor === k;
            });
            var unit = (s && s.sensor_meta && s.sensor_meta.unit) || '';
            if (!unit) return;
            if (activeSeries[k].axis === 'right') rightUnits[unit] = true;
            else leftUnits[unit] = true;
        });
        var leftKeys = Object.keys(leftUnits);
        var rightKeys = Object.keys(rightUnits);
        relayoutUpdate['yaxis.title.text'] = leftKeys.length === 1
            ? leftKeys[0] : '';
        relayoutUpdate['yaxis2.title.text'] = rightKeys.length === 1
            ? rightKeys[0] : '';
        Plotly.relayout(chartDiv, relayoutUpdate);
    }

    function updateStats() {
        if (statsDiv) {
            var t = 0;
            var truncatedKeys = [];
            Object.keys(activeSeries).forEach(function(k) {
                t += activeSeries[k].points || 0;
                if (activeSeries[k].truncated) {
                    truncatedKeys.push(k);
                }
            });
            var text = t > 0
                ? t.toLocaleString() + ' data points' : '';
            if (truncatedKeys.length > 0) {
                var limit = activeSeries[truncatedKeys[0]].limit;
                text += ' — ' + truncatedKeys.length
                    + (truncatedKeys.length === 1
                        ? ' series' : ' series')
                    + ' capped at '
                    + limit.toLocaleString()
                    + ' points (narrow the date range'
                    + ' to see all data)';
            }
            statsDiv.textContent = text;
            statsDiv.classList.toggle(
                'truncation-warning',
                truncatedKeys.length > 0);
        }
    }

    function showEmpty(show) {
        var el = document.getElementById('chart-empty');
        if (el) el.style.display = show ? 'flex' : 'none';
        chartDiv.style.display = show ? 'none' : 'block';
    }

    function syncUrl() {
        var left = [], right = [];
        Object.keys(activeSeries).sort().forEach(function(k) {
            if (activeSeries[k].axis === 'right') right.push(k);
            else left.push(k);
        });
        var p = new URLSearchParams(window.location.search);
        if (left.length) p.set('s', left.join(','));
        else p.delete('s');
        if (right.length) p.set('r', right.join(','));
        else p.delete('r');
        var newUrl = window.location.pathname;
        var qs = p.toString();
        if (qs) newUrl += '?' + qs;
        history.replaceState(null, '', newUrl);
        syncDateFormParams();
    }

    // Preserve s/r params across date filter submissions by
    // injecting hidden fields into the form. This works for both
    // the Apply button and the preset buttons (which call
    // form.submit() directly, bypassing the submit event).
    var dateForm = document.getElementById('dateFilter');
    if (dateForm) {
        var params = new URLSearchParams(window.location.search);
        ['s', 'r'].forEach(function(name) {
            var val = params.get(name);
            if (val) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = name;
                input.value = val;
                dateForm.appendChild(input);
            }
        });
    }

    // Also keep hidden fields in sync when series change
    function syncDateFormParams() {
        if (!dateForm) return;
        ['s', 'r'].forEach(function(name) {
            var existing = dateForm.querySelector(
                'input[name="' + name + '"]');
            var p = new URLSearchParams(window.location.search);
            var val = p.get(name);
            if (val) {
                if (existing) {
                    existing.value = val;
                } else {
                    var input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = name;
                    input.value = val;
                    dateForm.appendChild(input);
                }
            } else if (existing) {
                existing.remove();
            }
        });
    }
})();
"""

DASHBOARD_CSS = """
.dashboard-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
    gap: 1rem;
}
.dashboard-card {
    position: relative;
}
.dashboard-card .mini-chart {
    height: 250px;
    width: 100%;
}
.card-actions {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    z-index: 1;
}
.card-actions .delete-btn {
    padding: 0.1rem 0.4rem;
    font-size: 1.2rem;
    line-height: 1;
}
.card-title {
    cursor: pointer;
}
.card-title::after {
    content: ' \\270E';
    opacity: 0.3;
    font-size: 0.8em;
}
.card-link {
    display: block;
    margin-top: 0.5rem;
    font-size: 0.9rem;
}
.rename-input {
    margin-bottom: 0.5rem;
}
[data-theme="dark"] .mini-chart {
    filter: invert(0.88) hue-rotate(180deg);
}
"""

DASHBOARD_JS = """
(function() {
    var dashboardId = document.documentElement.dataset.dashboard || 'blue';
    var STORAGE_KEY = 'wp6-dashboard-' + dashboardId;
    var grid = document.getElementById('dashboard-grid');
    var emptyMsg = document.getElementById('dashboard-empty');

    function load() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return { version: 1, charts: [] };
            var data = JSON.parse(raw);
            return data && data.charts ? data : { version: 1, charts: [] };
        } catch (e) {
            return { version: 1, charts: [] };
        }
    }

    function save(data) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); }
        catch (e) { alert('Could not save dashboard: storage may be full.'); }
    }

    function resolveDate(chart) {
        if (chart.dateMode === 'relative') {
            var end = new Date();
            var start = new Date();
            start.setDate(start.getDate() - (chart.relativeDays || 7));
            return {
                start: start.toISOString().slice(0, 10),
                end: end.toISOString().slice(0, 10)
            };
        }
        return { start: chart.start, end: chart.end };
    }

    function buildChartUrl(chart) {
        var dates = resolveDate(chart);
        var params = new URLSearchParams();
        if (chart.s) params.set('s', chart.s);
        if (chart.r) params.set('r', chart.r);
        params.set('start', dates.start);
        params.set('end', dates.end);
        return '/chart?' + params.toString();
    }

    function renderCard(chart) {
        var article = document.createElement('article');
        article.className = 'dashboard-card';
        article.dataset.chartId = chart.id;

        var dates = resolveDate(chart);
        var dateLabel = chart.dateMode === 'relative'
            ? 'Last ' + chart.relativeDays + ' days'
            : dates.start + ' to ' + dates.end;

        article.innerHTML =
            '<div class="card-actions">' +
                '<button class="delete-btn outline secondary"' +
                ' title="Remove from dashboard">&times;</button>' +
            '</div>' +
            '<h4 class="card-title" title="Click to rename">' + escapeHtml(chart.title) + '</h4>' +
            '<small>' + dateLabel + '</small>' +
            '<div class="mini-chart"><progress></progress></div>' +
            '<a href="' + buildChartUrl(chart) + '" class="card-link">Open in chart &rarr;</a>';

        article.querySelector('.delete-btn').addEventListener('click', function() {
            deleteChart(chart.id);
            article.remove();
            var data = load();
            if (data.charts.length === 0) emptyMsg.style.display = 'block';
        });

        var titleEl = article.querySelector('.card-title');
        titleEl.addEventListener('click', function() {
            var input = document.createElement('input');
            input.type = 'text';
            input.value = chart.title;
            input.className = 'rename-input';
            titleEl.replaceWith(input);
            input.focus();
            input.select();
            function finishRename() {
                var newTitle = input.value.trim() || chart.title;
                renameChart(chart.id, newTitle);
                var newH4 = document.createElement('h4');
                newH4.className = 'card-title';
                newH4.title = 'Click to rename';
                newH4.textContent = newTitle;
                input.replaceWith(newH4);
                newH4.addEventListener('click', titleEl.onclick);
                titleEl = newH4;
            }
            input.addEventListener('blur', finishRename);
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
                if (e.key === 'Escape') { input.value = chart.title; input.blur(); }
            });
        });

        return article;
    }

    function loadMiniChart(chart, divElement) {
        var dates = resolveDate(chart);
        var allKeys = [];
        if (chart.s) chart.s.split(',').forEach(function(k) {
            allKeys.push({key: k, axis: 'left'});
        });
        if (chart.r) chart.r.split(',').forEach(function(k) {
            allKeys.push({key: k, axis: 'right'});
        });

        var promises = allKeys.map(function(item) {
            var parts = item.key.split(':');
            var url = '/api/series?device=' + encodeURIComponent(parts[0]) +
                '&sensor=' + encodeURIComponent(parts.slice(1).join(':')) +
                '&start=' + dates.start + '&end=' + dates.end;
            return fetch(url)
                .then(function(r) { return r.json(); })
                .then(function(json) {
                    return {key: item.key, axis: item.axis,
                        data: json.data || []};
                })
                .catch(function() {
                    return {key: item.key, axis: item.axis, data: []};
                });
        });

        Promise.all(promises).then(function(results) {
            var traces = results.map(function(r) {
                var trace = {
                    x: r.data.map(function(d) { return d.time; }),
                    y: r.data.map(function(d) { return d.value; }),
                    name: r.key,
                    mode: 'lines',
                    yaxis: r.axis === 'right' ? 'y2' : 'y'
                };
                if (r.axis === 'right') trace.line = { dash: 'dash' };
                return trace;
            });
            var hasRight = results.some(function(r) { return r.axis === 'right'; });
            var layout = {
                height: 250,
                margin: { t: 10, b: 30, l: 40, r: hasRight ? 40 : 10 },
                showlegend: false,
                xaxis: { type: 'date' },
                yaxis: {},
                yaxis2: { overlaying: 'y', side: 'right', showgrid: false },
                template: 'plotly_white',
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)'
            };
            divElement.innerHTML = '';
            if (traces.every(function(t) { return t.x.length === 0; })) {
                divElement.innerHTML =
                    '<p style="text-align:center;' +
                    'color:var(--pico-muted-color)">' +
                    'No data available</p>';
                return;
            }
            Plotly.newPlot(divElement, traces, layout, { displayModeBar: false, responsive: true });
        });
    }

    function deleteChart(id) {
        var data = load();
        data.charts = data.charts.filter(function(c) { return c.id !== id; });
        save(data);
    }

    function renameChart(id, newTitle) {
        var data = load();
        data.charts.forEach(function(c) { if (c.id === id) c.title = newTitle; });
        save(data);
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    var data = load();
    if (data.charts.length === 0) {
        emptyMsg.style.display = 'block';
        return;
    }
    emptyMsg.style.display = 'none';
    data.charts.forEach(function(chart) {
        var card = renderCard(chart);
        grid.appendChild(card);
        loadMiniChart(chart, card.querySelector('.mini-chart'));
    });
})();
"""

SAVE_TO_DASHBOARD_JS = """
(function() {
    var dashboardId = document.documentElement.dataset.dashboard || 'blue';
    var STORAGE_KEY = 'wp6-dashboard-' + dashboardId;
    var saveBtn = document.getElementById('save-to-dashboard');
    var dialog = document.getElementById('save-dialog');
    if (!saveBtn || !dialog) return;

    saveBtn.addEventListener('click', function() {
        var params = new URLSearchParams(window.location.search);
        var s = params.get('s') || '';
        var r = params.get('r') || '';
        if (!s && !r) { alert('Select some sensors first.'); return; }

        var allKeys = (s + (r ? ',' + r : '')).split(',').filter(Boolean);
        var suggested = allKeys.slice(0, 3).join(', ') + (allKeys.length > 3 ? ' ...' : '');
        dialog.querySelector('#save-title').value = suggested;

        var start = params.get('start');
        var end = params.get('end');
        var days = 7;
        if (start && end) {
            days = Math.round((new Date(end) - new Date(start)) / 86400000);
        }
        dialog.querySelector('#save-relative-days').value = days;
        dialog.querySelector('#save-date-mode').checked = true;
        dialog.querySelector('#save-days-group').style.display = '';

        dialog.showModal();
    });

    dialog.querySelector('#save-date-mode').addEventListener('change', function() {
        dialog.querySelector('#save-days-group').style.display = this.checked ? '' : 'none';
    });

    dialog.querySelector('#save-confirm').addEventListener('click', function() {
        var params = new URLSearchParams(window.location.search);
        var title = dialog.querySelector('#save-title').value.trim();
        if (!title) { alert('Please enter a title.'); return; }

        var isRelative = dialog.querySelector('#save-date-mode').checked;
        var chart = {
            id: Math.random().toString(36).slice(2, 10),
            title: title,
            s: params.get('s') || '',
            r: params.get('r') || '',
            dateMode: isRelative ? 'relative' : 'absolute',
            relativeDays: parseInt(dialog.querySelector('#save-relative-days').value) || 7,
            start: params.get('start') || '',
            end: params.get('end') || '',
            createdAt: new Date().toISOString()
        };

        var raw = localStorage.getItem(STORAGE_KEY);
        var data;
        try { data = raw ? JSON.parse(raw) : { version: 1, charts: [] }; }
        catch (e) { data = { version: 1, charts: [] }; }
        data.charts.push(chart);
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            alert('Could not save: storage may be full.');
            dialog.close();
            return;
        }

        dialog.close();
        var origText = saveBtn.textContent;
        saveBtn.textContent = 'Saved!';
        setTimeout(function() { saveBtn.textContent = origText; }, 2000);
    });

    dialog.querySelector('#save-cancel').addEventListener('click', function() {
        dialog.close();
    });
})();
"""



def _render_source_toggle(active_source: str | None) -> str:
    """Render a data-source <select> dropdown from the configured data sources."""
    if len(_data_sources) < 2:
        return ""
    options = "".join(
        f'<option value="{ds.key}"{" selected" if ds.key == active_source else ""}>'
        f"{ds.label}</option>"
        for ds in _data_sources
    )
    return (
        f'<select id="source-toggle" onchange="switchSource(this.value)"'
        f' style="width:auto;margin:0;padding:0.2rem 0.5rem;font-size:0.8rem">'
        f"{options}</select>"
    )


def _source_toggle_js() -> str:
    """Generate the cookie-setting JS for the source toggle."""
    if len(_data_sources) < 2:
        return ""
    cookie_name = f"wp6_{_dashboard_id}_source"
    return f"""
    function switchSource(value) {{
        document.cookie = '{cookie_name}=' + value + ';path=/;max-age=31536000';
        location.reload();
    }}
"""


def render_nav_bar(*, data_source: str | None = None) -> str:
    """Render a sticky nav bar with dashboard name, home link, and dark mode toggle."""
    name = _dashboard_title
    user = _current_user.get()
    user_html = (
        f'<span class="nav-user">{user} | <a href="/auth/logout">Logout</a></span>'
        if user
        else ""
    )
    source_html = _render_source_toggle(data_source) if data_source else ""
    return f"""
    <nav class="dashboard-nav">
        <a href="/" class="brand">{name}</a>
        <div class="nav-links">
            <a href="/">Home</a>
            <a href="/dashboard">Dashboard</a>
            <a href="/chart">Chart</a>
            {user_html}
            {source_html}
            <button id="theme-toggle" title="Toggle dark mode">
                <span class="icon-sun">&#9788;</span>
                <span class="icon-moon">&#9790;</span>
            </button>
        </div>
    </nav>
    """


def render_page(
    title: str,
    content: str,
    *,
    show_logo: bool = True,
    show_footer: bool = True,
    show_back_link: bool = False,
    back_url: str = "/",
    extra_css: str = "",
    data_source: str | None = None,
) -> str:
    """Render a complete HTML page with consistent styling.

    Args:
        title: Page title
        content: Main HTML content
        show_logo: Show Interreg logo at top
        show_footer: Show footer with logo
        show_back_link: Show back navigation link
        back_url: URL for back link
        extra_css: Additional CSS rules

    Returns:
        Complete HTML document as string
    """
    back_html = (
        f'<div class="back"><a href="{back_url}">&larr; Home</a></div>'
        if show_back_link
        else ""
    )

    footer_html = (
        '<footer><img src="/static/interreg.png" alt="Interreg" class="footer-logo"></footer>'
        if show_footer
        else ""
    )

    return f"""
    <!DOCTYPE html>
    <html data-dashboard="{_dashboard_id}">
    <head>
        <title>{title}</title>
        <link rel="icon" href="/static/favicon.ico" type="image/x-icon">
        <link rel="stylesheet"
              href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css">
        <script>{THEME_JS}</script>
        <style>
            {BASE_CSS}
            {_twin_theme_css}
            {extra_css}
        </style>
    </head>
    <body>
        {render_nav_bar(data_source=data_source)}
        <main>
            {back_html}
            {content}
            {footer_html}
        </main>
        <script>{TOGGLE_JS}</script>
        <script>{_source_toggle_js()}</script>
        <script>{TABLE_SORT_JS}</script>
    </body>
    </html>
    """


def render_unified_chart_page(
    title_prefix: str,
    start: date,
    end: date,
    *,
    data_source: str | None = None,
) -> str:
    """Render the unified chart page with side panel and on-demand data loading.

    The page starts empty; client-side JS fetches sensor list and series data.
    URL params ``s`` and ``r`` encode the selected series for bookmarking.

    Args:
        title_prefix: Page title prefix
        start: Start date for the date-range filter.
        end: End date for the date-range filter.
        data_source: Optional data source identifier (blue twin).

    Returns:
        Complete HTML page string.
    """
    filter_html = render_date_filter(start, end)

    content = f"""
    <div class="chart-layout">
        <div class="sensor-panel" id="sensor-panel-wrapper">
            <details class="date-filter-collapsible" open>
                <summary>Date range: {start.isoformat()} \
to {end.isoformat()}</summary>
                {filter_html}
            </details>
            <h4>Sensors <a href="#" id="clear-all"
                class="clear-btn" title="Clear all selections"
                >[x]</a></h4>
            <div class="group-toggle">
                <button class="group-btn active" data-group="measurement"
                    >By type</button>
                <button class="group-btn" data-group="device"
                    >By device</button>
                <button class="group-btn" data-group="position"
                    >By position</button>
            </div>
            <div id="sensor-panel">Loading sensors...</div>
        </div>
        <div class="chart-main">
            <button class="panel-toggle outline" id="panel-toggle">
                Hide controls</button>
            <button class="panel-toggle outline" id="save-to-dashboard"
                title="Save current chart view to dashboard">&#9734; Save</button>
            <div class="chart-stats" id="chart-stats"></div>
            <div class="chart-empty" id="chart-empty">
                Select sensors from the panel to start charting</div>
            <div id="chart-area"></div>
        </div>
    <dialog id="save-dialog">
        <article>
            <header>Save to Dashboard</header>
            <label for="save-title">Title</label>
            <input type="text" id="save-title" placeholder="Chart title">
            <label>
                <input type="checkbox" id="save-date-mode" checked>
                Use rolling date range
            </label>
            <div id="save-days-group">
                <label for="save-relative-days">Number of days</label>
                <input type="number" id="save-relative-days" min="1" value="7">
            </div>
            <footer>
                <button id="save-cancel" class="secondary">Cancel</button>
                <button id="save-confirm">Save</button>
            </footer>
        </article>
    </dialog>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>{UNIFIED_CHART_JS}</script>
    <script>{SAVE_TO_DASHBOARD_JS}</script>
    """

    title = f"{title_prefix} — Chart"
    # TODO: a nice title would be nice both here and in the chart.
    # e.g. "Temperature and humidity over time"

    return render_page(
        title,
        content,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
        data_source=data_source,
    )


def render_dashboard_page(
    title_prefix: str,
    *,
    data_source: str | None = None,
) -> str:
    """Render the dashboard page showing saved chart bookmarks as live mini-charts."""
    content = f"""
    <h2>Dashboard</h2>
    <p><small>Your dashboard is stored in this browser's local storage
    and won't appear on other devices.</small></p>
    <p id="dashboard-empty" style="display:none">
        No saved charts yet. <a href="/chart">Open the chart</a> and use
        the save button to bookmark views here.</p>
    <div class="dashboard-grid" id="dashboard-grid"></div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>{DASHBOARD_JS}</script>
    """
    return render_page(
        f"{title_prefix} — Dashboard",
        content,
        show_logo=False,
        show_footer=True,
        extra_css=DASHBOARD_CSS,
        data_source=data_source,
    )
