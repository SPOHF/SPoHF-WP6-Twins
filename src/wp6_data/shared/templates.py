"""Shared HTML templates for WP6 dashboards."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

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


def render_hub_card(
    title: str,
    description: str = "",
    *,
    href: str = "",
    label: str = "Open",
    body: str = "",
    card_class: str = "",
    disabled: bool = False,
) -> str:
    """Render a hub navigation card: heading, description, optional body, action button.

    Used by overview/hub pages that link out to detailed views (DLI dashboard,
    Plant Monitor, Multi Height). Pass ``disabled=True`` for a non-clickable button
    (e.g. an admin-gated action); ``body`` injects extra HTML before the button.
    """
    desc = f"<p>{description}</p>" if description else ""
    if disabled:
        action = f'<span class="btn-disabled">{label}</span>'
    else:
        action = f'<a href="{href}" class="btn">{label}</a>'
    cls = f' class="{card_class}"' if card_class else ""
    return f"<article{cls}><h3>{title}</h3>{desc}{body}{action}</article>"


def render_hub_grid(cards: list[str]) -> str:
    """Wrap hub navigation cards in a responsive auto-fit grid."""
    return f'<div class="hub-grid">{"".join(cards)}</div>'


def render_table(
    headers: list[str], rows: list[list[str]], *,
    sortable: bool = True, group_col: int | None = None,
) -> str:
    """Render an HTML table from headers and row data (cells may contain HTML).

    When *group_col* is set, the table is marked with ``data-group-col`` so that
    the front-end can visually merge consecutive identical values in that column
    while it is the active sort.
    """
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
    table_attrs = (
        f' data-group-col="{group_col}"' if group_col is not None else ""
    )
    return (
        f"<table{table_attrs}><thead>{thead}</thead>"
        f"<tbody>{tbody}</tbody></table>"
    )


EXPLORE_TAB_IDS = ("devices", "sensors", "manual")
EXPLORE_TAB_LABELS = {
    "devices": "Devices",
    "sensors": "Sensors",
    "manual": "Manual measurements",
}


def _format_timestamp_cell(dt: Any) -> tuple[str, str]:
    """Render a datetime as an HTML cell tuple (display, sort_key).

    Display is a relative phrase ("3 hours ago"); sort_key is the ISO string
    so client-side sort orders by absolute time. ``None`` renders as a dash.
    """
    if dt is None:
        return ("—", "")

    from datetime import datetime

    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        delta = now - dt
        seconds = delta.total_seconds()
        if seconds < 60:
            phrase = "just now"
        elif seconds < 3600:
            phrase = f"{int(seconds // 60)} min ago"
        elif seconds < 86400:
            phrase = f"{int(seconds // 3600)} h ago"
        elif seconds < 7 * 86400:
            phrase = f"{int(seconds // 86400)} d ago"
        else:
            phrase = dt.strftime("%Y-%m-%d")
        # Tooltip carries the absolute UTC timestamp for precision.
        title = dt.strftime("%Y-%m-%d %H:%M UTC")
        html = f'<span title="{title}">{phrase}</span>'
        return (html, dt.isoformat())
    return (str(dt), str(dt))


def build_explore_tabs(
    metadata: MetadataRegistry,
    devices: dict[str, dict],
    available_exports: dict[str, str],
    manual_metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build the three explore tables (devices, sensors, manual measurements).

    Sensors are split by ``sensor_default(key).source``: empty source = auto-
    logged, non-empty = manual upload. Devices are similarly filtered by
    ``device(id).source`` so that manual-measurement plants do not appear in
    the Devices tab.

    Args:
        metadata: The twin's metadata registry.
        devices: ``{device_id: {"sensors": [str], "readings": int,
                              "last_seen": datetime | None}}``.
        available_exports: Export availability dict for download links.
        manual_metadata: ``{"uploads": {source: datetime},
                           "measurements": {sensor_key: datetime}}``
            from the provider's ``fetch_manual_metadata``.

    Returns:
        ``{"devices": html, "sensors": html, "manual": html}``
    """
    manual_metadata = manual_metadata or {"uploads": {}, "measurements": {}}
    manual_uploads = manual_metadata.get("uploads", {})
    manual_measurements = manual_metadata.get("measurements", {})
    from wp6_data.shared.export import render_download_link

    # --- Aggregate per-sensor: total readings + set of devices ---
    sensor_readings: dict[str, int] = {}
    sensor_devices: dict[str, set[str]] = {}
    for device_id, info in devices.items():
        for s in info["sensors"]:
            sensor_readings[s] = sensor_readings.get(s, 0) + info["readings"]
            sensor_devices.setdefault(s, set()).add(device_id)

    auto_entries: list[dict[str, str]] = []
    manual_entries: list[dict[str, str]] = []
    for key in sorted(sensor_readings, key=lambda k: -sensor_readings[k]):
        sm = metadata.sensor_default(key)
        entry = {
            "key": key,
            "url": chart_url([
                f"{d}:{key}" for d in sorted(sensor_devices.get(key, set()))
            ]),
            "type": sm.type,
            "alias": sm.alias,
            "unit": sm.unit,
            "Devices": ", ".join(sorted(sensor_devices.get(key, set()))),
            "Readings": f"{sensor_readings[key]:,}",
            "Source": sm.source,
        }
        if sm.source:
            entry["Last upload"] = _format_timestamp_cell(
                manual_uploads.get(sm.source),
            )
            entry["Last measure"] = _format_timestamp_cell(
                manual_measurements.get(key),
            )
            manual_entries.append(entry)
        else:
            auto_entries.append(entry)

    sensors_tab = render_sensor_type_table(
        auto_entries, extra_headers=["Devices", "Readings"],
    )
    if manual_entries:
        manual_tab = render_manual_measurement_table(
            manual_entries,
            extra_headers=["Readings", "Last upload", "Last measure"],
        )
    else:
        manual_tab = (
            "<p>No manual measurements have been uploaded yet.</p>"
        )

    # --- Devices tab: only auto-logged hardware (source == "") ---
    auto_devices = {
        device_id: info
        for device_id, info in devices.items()
        if not metadata.device(device_id).source
    }

    position_series: dict[str, list[str]] = {}
    dtype_series: dict[str, list[str]] = {}
    for device_id, info in auto_devices.items():
        dm = metadata.device(device_id)
        series = [f"{device_id}:{s}" for s in sorted(info["sensors"])]
        if dm.position:
            position_series.setdefault(dm.position, []).extend(series)
        if dm.type:
            dtype_series.setdefault(dm.type, []).extend(series)

    device_entries = []
    for device_id, info in sorted(auto_devices.items()):
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
            f'<strong><a href="{chart_url(dtype_series[dm.type])}">'
            f"{dm.type}</a></strong>"
            if dm.type
            else ""
        )
        # Manual sources (devices whose readings come from a manually-uploaded
        # file rather than an automated sensor) get a small badge so users can
        # tell measurement plants apart from sensor stations at a glance.
        source_badge = (
            f' <small><mark>manual: {dm.source}</mark></small>'
            if dm.source else ""
        )
        device_entries.append({
            "name": (
                f'<strong><a href="{chart_url(dev_series)}">{device_id}</a>'
                f"</strong>{source_badge}"
            ),
            "position": pos_html,
            "type": type_html,
            "type_sort": dm.type,
            "sensors": sensor_links,
            "readings": f'{info["readings"]:,}' if info["readings"] else "",
            "Last seen": _format_timestamp_cell(info.get("last_seen")),
            "Download": render_download_link(device_id, available_exports),
        })
    devices_tab = render_device_table(
        device_entries, extra_columns=["Last seen", "Download"],
    )

    return {
        "devices": devices_tab,
        "sensors": sensors_tab,
        "manual": manual_tab,
    }


def render_explore_tabs(tabs: dict[str, str], active: str = "devices") -> str:
    """Wrap the explore tables in a tab switcher.

    Args:
        tabs: ``{tab_id: html}`` content for each tab.
        active: Initially-selected tab id; falls back to "devices" if invalid.
    """
    if active not in EXPLORE_TAB_IDS:
        active = "devices"

    buttons = "".join(
        f'<button type="button" role="tab" data-tab="{tid}"'
        f' aria-selected="{"true" if tid == active else "false"}">'
        f"{EXPLORE_TAB_LABELS[tid]}</button>"
        for tid in EXPLORE_TAB_IDS
    )
    panels = "".join(
        f'<div role="tabpanel" data-tab-panel="{tid}"'
        f'{"" if tid == active else " hidden"}>'
        f'{tabs.get(tid, "")}</div>'
        for tid in EXPLORE_TAB_IDS
    )

    return (
        '<div class="explore-tabs">'
        f'<div class="tab-buttons" role="tablist">{buttons}</div>'
        f"{panels}"
        "</div>"
    )


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
        for s in type_groups[sensor_type]:
            type_html = (
                f'<strong><a href="/type/{sensor_type}">'
                f"{sensor_type}</a></strong>"
            )
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

    return render_table(headers, rows, group_col=0)


def render_manual_measurement_table(
    measurements: list[dict[str, Any]],
    *,
    extra_headers: list[str] | None = None,
) -> str:
    """Render a manual-measurement table grouped by source (column 0).

    Each dict in *measurements* should have keys:
        - ``key``: measurement key
        - ``url``: link for the measurement name
        - ``type``: sensor type label (e.g. "fruit chemistry")
        - ``alias``: display name for the measurement
        - ``unit``: unit of measurement
        - ``Source``: source string (e.g. "sijia")
    Plus any extra keys matching *extra_headers*.
    """
    from collections import defaultdict as _defaultdict

    source_groups: dict[str, list[dict[str, Any]]] = _defaultdict(list)
    for m in measurements:
        source_groups[m.get("Source", "")].append(m)

    headers = ["Source", "Type", "Measurement", "Unit"]
    if extra_headers:
        headers.extend(extra_headers)

    rows: list[list] = []
    for source in sorted(source_groups):
        for m in source_groups[source]:
            source_cell = (f"<strong>{source}</strong>", source)
            sensor_type = m.get("type", "")
            type_cell = (
                (
                    f'<a href="/type/{sensor_type}">{sensor_type}</a>',
                    sensor_type,
                )
                if sensor_type
                else ("", "")
            )
            row: list = [
                source_cell,
                type_cell,
                f'<a href="{m["url"]}">{m.get("alias") or m["key"]}</a>',
                m.get("unit", ""),
            ]
            if extra_headers:
                for h in extra_headers:
                    row.append(m.get(h, ""))
            rows.append(row)

    return render_table(headers, rows, group_col=0)


def render_device_table(
    devices: list[dict[str, str]],
    *,
    extra_columns: list[str] | None = None,
) -> str:
    """Render a device table grouped by device type (column 0).

    Devices without a type land in a single un-typed bucket sorted last.

    Each dict in *devices* should have keys:
        - ``name``: device name/id (displayed as-is, may contain HTML links)
        - ``position``: from device metadata
        - ``type``: device type label
        - ``type_sort``: raw type string for sort/grouping (defaults to ``type``)
        - ``sensors``: comma-separated sensor aliases
        - ``readings``: formatted reading count
    Plus any extra keys matching *extra_columns* headers.
    """
    headers = ["Type", "Device", "Position", "Sensors", "Readings"]
    if extra_columns:
        headers.extend(extra_columns)

    # Group by type_sort (raw type) so the merge-cell JS can identify groups.
    grouped: dict[str, list[dict[str, str]]] = {}
    for d in devices:
        grouped.setdefault(d.get("type_sort", ""), []).append(d)

    # Empty-type bucket sorts last by using a high-codepoint sentinel.
    def _sort_key(t: str) -> tuple[int, str]:
        return (1, "") if t == "" else (0, t)

    rows: list[list] = []
    for type_key in sorted(grouped, key=_sort_key):
        for d in grouped[type_key]:
            row: list = [
                (d.get("type", ""), type_key),
                d.get("name", ""),
                d.get("position", ""),
                d.get("sensors", ""),
                d.get("readings", ""),
            ]
            if extra_columns:
                for col in extra_columns:
                    row.append(d.get(col, ""))
            rows.append(row)

    return render_table(headers, rows, group_col=0)


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
    .dashboard-nav .nav-links { display: flex; align-items: center; gap: 0; }
    .dashboard-nav .nav-group { display: flex; align-items: center; gap: 1rem; }
    .dashboard-nav .nav-group + .nav-group::before {
        content: ""; display: block;
        width: 1px; height: 1.2rem; margin: 0 1rem;
        background: currentColor; opacity: 0.2;
    }
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

    /* --- Hub pages: responsive grid of navigation cards --- */
    .hub-grid { display: grid; gap: 20px;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
    .hub-grid article { margin-bottom: 0; }
    .hub-grid article h3 { margin-top: 0; }
    .card-disabled { opacity: 0.6; }
    .btn { display: inline-block; padding: 8px 16px;
           background: var(--pico-primary-background);
           color: var(--pico-primary-inverse);
           text-decoration: none; border-radius: 4px; margin-right: 8px; }
    .btn:hover { opacity: 0.85; text-decoration: none; }
    .btn-disabled { display: inline-block; padding: 8px 16px; background: #ccc;
                    color: #666; border-radius: 4px; font-size: 0.9em; }

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
    .card-bg-multi-height::after {
        background-image: url(/static/cards/multi_height.svg);
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

    /* --- Explore tabs --- */
    .explore-tabs .tab-buttons {
        display: flex; gap: 0.25rem;
        border-bottom: 1px solid var(--pico-muted-border-color);
        margin-bottom: 1rem;
    }
    .explore-tabs .tab-buttons button {
        background: transparent; border: 0; border-radius: 0;
        border-bottom: 2px solid transparent;
        color: var(--pico-muted-color); cursor: pointer;
        margin: 0 0 -1px 0; padding: 0.5rem 0.9rem;
        width: auto; font-weight: 600;
    }
    .explore-tabs .tab-buttons button:hover { color: var(--pico-color); }
    .explore-tabs .tab-buttons button[aria-selected="true"] {
        color: var(--dashboard-primary);
        border-bottom-color: var(--dashboard-primary);
    }

    /* --- Tables --- */
    /* Grouped tables: hide content of merged duplicate cells without
       collapsing the cell itself (keeps row borders & widths consistent). */
    td.cell-merged > * { display: none; }

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
    body:has(.chart-layout) main {
        max-width: none;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
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
    .group-btn, .label-btn, .agg-btn, .ct-btn {
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
    .group-btn:not(:last-child), .label-btn:not(:last-child),
    .agg-btn:not(:last-child), .ct-btn:not(:last-child) {
        border-right: 1px solid var(--dashboard-primary);
    }
    .group-btn.active, .label-btn.active, .agg-btn.active, .ct-btn.active {
        background: var(--dashboard-primary);
        color: #fff;
    }
    .group-btn:not(.active):hover, .label-btn:not(.active):hover,
    .agg-btn:not(.active):hover, .ct-btn:not(.active):hover {
        background: color-mix(in srgb, var(--dashboard-primary) 12%, transparent);
    }
    /* Y-Left / Y-Right axis tabs: an underline tab strip, deliberately
       distinct from the filled segmented toggles below it. */
    .axis-tabs {
        display: flex;
        gap: 0.25rem;
        margin-bottom: 0.6rem;
        border-bottom: 2px solid
            color-mix(in srgb, var(--dashboard-primary) 25%, transparent);
    }
    .axis-tab {
        flex: 1;
        padding: 0.4rem 0.5rem;
        cursor: pointer;
        border: none;
        background: transparent;
        color: var(--dashboard-primary);
        font-size: 0.8rem;
        border-bottom: 2px solid transparent;
        margin-bottom: -2px;
        opacity: 0.55;
        transition: opacity 0.15s, border-color 0.15s;
    }
    .axis-tab.active {
        border-bottom-color: var(--dashboard-primary);
        font-weight: 700;
        opacity: 1;
    }
    .axis-tab:not(.active):hover { opacity: 0.85; }
    .ct-icon {
        width: 11px;
        height: 11px;
        vertical-align: -1px;
        margin-right: 4px;
        opacity: 0.85;
    }
    .bucket-slider {
        font-size: 0.75rem;
        margin: 0.3rem 0;
    }
    .bucket-slider input[type="range"] {
        width: 100%;
        margin: 0.2rem 0 0;
    }
    .band-toggle {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.8rem;
        margin: 0.4rem 0 0;
        cursor: pointer;
    }
    .band-toggle input[type="checkbox"] {
        margin: 0;
        width: auto;
    }
    .band-hint {
        display: block;
        font-size: 0.7rem;
        opacity: 0.65;
        margin: 0 0 0.3rem 1.4rem;
    }
    /* "Show but disable": the band only applies to a true range (an active
       aggregation other than SUM), so grey it out when it cannot apply. */
    .band-toggle.disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }
    /* --- Ideal range section --- */
    .ideal-range-section {
        margin-top: 0.6rem;
    }
    .ideal-range-section h4 {
        font-size: 0.82rem;
        font-weight: 600;
        margin: 0.2rem 0 0.25rem;
        color: var(--dashboard-primary);
    }
    .ideal-range-inputs {
        display: flex;
        align-items: center;
        gap: 0.3rem;
    }
    .ideal-input {
        font-size: 0.75rem;
        padding: 0.15rem 0.3rem;
        flex: 1;
        min-width: 0;
        width: auto;
    }
    .ideal-range-section.disabled {
        opacity: 0.45;
        pointer-events: none;
    }
    .advanced-options {
        margin-top: 0.6rem;
    }
    .advanced-options > summary {
        font-size: 0.82rem;
        font-weight: 600;
        color: var(--dashboard-primary);
        cursor: pointer;
    }
    .advanced-options .advanced-inner {
        margin-top: 0.4rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .advanced-toggle {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.8rem;
        margin: 0;
        cursor: pointer;
    }
    .advanced-toggle input[type="checkbox"] {
        margin: 0;
        width: auto;
        appearance: auto;
        -webkit-appearance: checkbox;
        accent-color: var(--dashboard-primary);
        transform: scale(1.05);
        transform-origin: center;
    }
    .chart-warning {
        margin: 0.35rem 0 0.5rem;
        padding: 0.45rem 0.65rem;
        border: 1px solid rgba(245, 158, 11, 0.45);
        background: rgba(245, 158, 11, 0.08);
        border-radius: 8px;
        font-size: 0.82rem;
    }
    .axis-split-toggle {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.8rem;
        margin: 0.5rem 0 0.3rem;
        cursor: pointer;
    }
    .axis-split-toggle input[type="checkbox"] {
        margin: 0;
    }
    #axis-controls-split h4 {
        margin: 0.6rem 0 0.2rem;
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

EXPLORE_TABS_JS = """
    (function() {
        var root = document.querySelector('.explore-tabs');
        if (!root) return;
        var buttons = root.querySelectorAll('[data-tab]');
        var panels = root.querySelectorAll('[data-tab-panel]');
        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                var id = btn.dataset.tab;
                buttons.forEach(function(b) {
                    b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
                });
                panels.forEach(function(p) {
                    p.hidden = p.dataset.tabPanel !== id;
                });
                var url = new URL(window.location.href);
                url.searchParams.set('tab', id);
                history.replaceState(null, '', url.toString());
            });
        });
    })();
"""


TABLE_SORT_JS = """
    function refreshGrouping(table) {
        var raw = table.dataset.groupCol;
        if (raw === undefined) return;
        var groupCol = parseInt(raw, 10);
        if (isNaN(groupCol)) return;
        // Find which header (if any) currently drives the sort.
        var ths = table.querySelectorAll('thead th');
        var sortedIdx = null;
        ths.forEach(function(th, i) {
            if (th.dataset.sortDir === 'asc' || th.dataset.sortDir === 'desc') {
                sortedIdx = i;
            }
        });
        // Merge only when no sort is active (initial render) or the active
        // sort matches the group column — otherwise rows aren't grouped.
        var shouldMerge = (sortedIdx === null || sortedIdx === groupCol);
        var rows = table.querySelectorAll('tbody tr');
        if (!shouldMerge) {
            rows.forEach(function(r) {
                var c = r.children[groupCol];
                if (c) c.classList.remove('cell-merged');
            });
            return;
        }
        var prev = null;
        rows.forEach(function(row) {
            var cell = row.children[groupCol];
            if (!cell) return;
            var key = cell.dataset.sort || cell.textContent.trim();
            if (key === prev) cell.classList.add('cell-merged');
            else { cell.classList.remove('cell-merged'); prev = key; }
        });
    }

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
        refreshGrouping(table);
    }

    document.querySelectorAll('table[data-group-col]').forEach(refreshGrouping);
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
    var seriesData = {};  // key -> {times: [], values: []}
    var totalPoints = 0;
    var BUCKET_STEPS = [0, 1, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 10080, 20160, 43200];

    var splitMode = false;
    var idealLo = null;
    var idealHi = null;
    var fertigationOverlay = false;
    var fertigationEvents = [];
    var fertigationFirstDate = null;
    var fertigationLastDate = null;
    var fertigationTotalEvents = 0;
    var fertigationLoadError = false;
    function defaultAxisCfg() {
        return {
            labelFormat: 'smart',
            chartType: 'line',
            aggregateEnabled: false,
            aggregateFunc: 'avg',
            bucketMinutes: 10,
            bandEnabled: false
        };
    }
    var axisCfg = { left: defaultAxisCfg(), right: defaultAxisCfg() };
    function cfgFor(axis) { return splitMode ? axisCfg[axis] : axisCfg.left; }

    // Parse URL params
    var params = new URLSearchParams(window.location.search);
    var leftSpecs = (params.get('s') || '').split(',').filter(Boolean);
    var rightSpecs = (params.get('r') || '').split(',').filter(Boolean);
    var startDate = params.get('start') || '';
    var endDate = params.get('end') || '';

    function readLabelFormat(name, fallback) {
        var v = params.get(name) || '';
        return ['smart', 'short', 'raw'].indexOf(v) !== -1 ? v : fallback;
    }
    function readChartType(name, fallback) {
        var v = params.get(name) || '';
        return ['line', 'scatter', 'box'].indexOf(v) !== -1 ? v : fallback;
    }
    function readAggInto(cfg, aggName, bktName, bandName) {
        var agg = params.get(aggName);
        if (agg === 'off') {
            cfg.aggregateEnabled = false;
        } else if (agg && ['avg', 'max', 'min', 'sum'].indexOf(agg) !== -1) {
            cfg.aggregateEnabled = true;
            cfg.aggregateFunc = agg;
        }
        var bkt = parseInt(params.get(bktName));
        if (!isNaN(bkt) && BUCKET_STEPS.indexOf(bkt) !== -1) {
            cfg.bucketMinutes = bkt;
        }
        var band = params.get(bandName);
        if (band === '1') cfg.bandEnabled = true;
        else if (band === '0') cfg.bandEnabled = false;
    }
    axisCfg.left.labelFormat = readLabelFormat('lbl', 'smart');
    axisCfg.left.chartType = readChartType('ct', 'line');
    readAggInto(axisCfg.left, 'agg', 'bkt', 'band');
    var _idealLoRaw = parseFloat(params.get('ideal_lo'));
    var _idealHiRaw = parseFloat(params.get('ideal_hi'));
    if (Number.isFinite(_idealLoRaw)) idealLo = _idealLoRaw;
    if (Number.isFinite(_idealHiRaw)) idealHi = _idealHiRaw;
    fertigationOverlay = params.get('fert_events') === '1';
    if (params.get('split') === '1') {
        splitMode = true;
        // Right-axis values fall back to left for any param not explicitly set
        axisCfg.right.labelFormat = readLabelFormat('lbl_r', axisCfg.left.labelFormat);
        axisCfg.right.chartType = readChartType('ct_r', axisCfg.left.chartType);
        axisCfg.right.aggregateEnabled = axisCfg.left.aggregateEnabled;
        axisCfg.right.aggregateFunc = axisCfg.left.aggregateFunc;
        axisCfg.right.bucketMinutes = axisCfg.left.bucketMinutes;
        axisCfg.right.bandEnabled = axisCfg.left.bandEnabled;
        readAggInto(axisCfg.right, 'agg_r', 'bkt_r', 'band_r');
    }

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
        yaxis2: {overlaying: 'y', side: 'right', showgrid: false},
        boxmode: 'group'
    };
    Plotly.newPlot(chartDiv, [], layout, {responsive: true});
    chartDiv.on('plotly_relayout', function() {
        updateFertigationWarning();
    });

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
            seriesData = {};
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
            updateFertigationWarning();
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

    function activeAggValueFor(axis) {
        var c = axisCfg[axis];
        return c.aggregateEnabled ? c.aggregateFunc : 'off';
    }

    function refreshControlActiveStates() {
        document.querySelectorAll('.ct-btn').forEach(function(btn) {
            var axis = btn.dataset.axis;
            btn.classList.toggle('active',
                btn.dataset.ct === axisCfg[axis].chartType);
        });
        document.querySelectorAll('.label-btn').forEach(function(btn) {
            var axis = btn.dataset.axis;
            btn.classList.toggle('active',
                btn.dataset.label === axisCfg[axis].labelFormat);
        });
        document.querySelectorAll('.agg-btn').forEach(function(btn) {
            var axis = btn.dataset.axis;
            var isBox = axisCfg[axis].chartType === 'box';
            btn.classList.toggle('active',
                btn.dataset.agg === activeAggValueFor(axis));
            // Boxplots ignore the aggregate func — only the slider matters.
            btn.disabled = isBox;
            btn.title = isBox ? 'Ignored for boxplots — the slider sets box width' : '';
        });
        document.querySelectorAll('.bucket-slider-input').forEach(function(slider) {
            var axis = slider.dataset.axis;
            var c = axisCfg[axis];
            var isBox = c.chartType === 'box';
            var idx = BUCKET_STEPS.indexOf(c.bucketMinutes);
            if (idx < 0) idx = 3;
            slider.value = idx;
            // Box keeps the slider live (it sets box width); otherwise the
            // slider only applies when aggregation is on.
            slider.disabled = isBox ? false : !c.aggregateEnabled;
            var labelEl = slider.parentElement.querySelector(
                '.bucket-label[data-axis="' + axis + '"]');
            if (labelEl) labelEl.textContent = formatBucket(c.bucketMinutes);
            var prefixEl = slider.parentElement.querySelector(
                '.bucket-prefix[data-axis="' + axis + '"]');
            if (prefixEl) prefixEl.textContent = isBox ? 'Box width:' : 'Bucket:';
        });
        document.querySelectorAll('.band-input').forEach(function(box) {
            var c = axisCfg[box.dataset.axis];
            // The range band is a line concept; a box already shows spread.
            var applies = bandAppliesTo(c) && c.chartType !== 'box';
            box.checked = c.bandEnabled;
            box.disabled = !applies;
            var label = box.closest('.band-toggle');
            if (label) label.classList.toggle('disabled', !applies);
        });
    }

    function wireAxisControls(rootEl) {
        rootEl.querySelectorAll('.ct-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var axis = btn.dataset.axis;
                var ct = btn.dataset.ct;
                if (ct === axisCfg[axis].chartType) return;
                var wasBox = axisCfg[axis].chartType === 'box';
                axisCfg[axis].chartType = ct;
                refreshControlActiveStates();
                // Box fetches raw while non-box-with-agg fetches bucketed, so
                // crossing the box boundary changes the data shape and needs a
                // refetch. line<->scatter share the same data — re-render only.
                if (wasBox !== (ct === 'box')) {
                    refetchAll();
                } else {
                    rebuildTraces();
                    syncUrl();
                }
            });
        });
        rootEl.querySelectorAll('.label-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var axis = btn.dataset.axis;
                var fmt = btn.dataset.label;
                if (fmt === axisCfg[axis].labelFormat) return;
                axisCfg[axis].labelFormat = fmt;
                refreshControlActiveStates();
                relabelAllTraces();
                syncUrl();
            });
        });
        rootEl.querySelectorAll('.agg-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var axis = btn.dataset.axis;
                var fn = btn.dataset.agg;
                if (fn === activeAggValueFor(axis)) return;
                if (fn === 'off') {
                    axisCfg[axis].aggregateEnabled = false;
                } else {
                    axisCfg[axis].aggregateEnabled = true;
                    axisCfg[axis].aggregateFunc = fn;
                }
                refreshControlActiveStates();
                refetchAll();
            });
        });
        rootEl.querySelectorAll('.bucket-slider-input').forEach(function(slider) {
            slider.addEventListener('input', function() {
                var axis = slider.dataset.axis;
                var minutes = BUCKET_STEPS[parseInt(slider.value)];
                var labelEl = slider.parentElement.querySelector(
                    '.bucket-label[data-axis="' + axis + '"]');
                if (labelEl) labelEl.textContent = formatBucket(minutes);
            });
            slider.addEventListener('change', function() {
                var axis = slider.dataset.axis;
                axisCfg[axis].bucketMinutes = BUCKET_STEPS[parseInt(slider.value)];
                if (axisCfg[axis].chartType === 'box') {
                    // Box width is a pure client-side regroup of raw points.
                    rebuildTraces();
                    syncUrl();
                } else if (axisCfg[axis].aggregateEnabled) {
                    refetchAll();
                }
            });
        });
        rootEl.querySelectorAll('.band-input').forEach(function(box) {
            box.addEventListener('change', function() {
                var axis = box.dataset.axis;
                axisCfg[axis].bandEnabled = box.checked;
                // min/max are already on the client whenever aggregation is
                // on, so toggling the band is a pure re-render — no refetch.
                rebuildTraces();
                syncUrl();
            });
        });
    }

    var unifiedBlock = document.getElementById('axis-controls-unified');
    var splitBlock = document.getElementById('axis-controls-split');
    if (unifiedBlock) wireAxisControls(unifiedBlock);
    if (splitBlock) wireAxisControls(splitBlock);

    function applySplitVisibility() {
        if (unifiedBlock) unifiedBlock.style.display = splitMode ? 'none' : '';
        if (splitBlock)   splitBlock.style.display   = splitMode ? '' : 'none';
    }

    function axisPresence() {
        var hasLeft = false;
        var hasRight = false;
        Object.keys(activeSeries).forEach(function(k) {
            if (activeSeries[k].axis === 'right') hasRight = true;
            else hasLeft = true;
        });
        return { hasLeft: hasLeft, hasRight: hasRight };
    }

    function hasDualAxesActive() {
        var presence = axisPresence();
        return presence.hasLeft && presence.hasRight;
    }

    function idealRangeAxisRef() {
        var presence = axisPresence();
        return presence.hasRight && !presence.hasLeft ? 'y2' : 'y';
    }

    function applyIdealRangeAvailability() {
        var disableIdeal = hasDualAxesActive();
        var idealSection = document.getElementById('ideal-range-section');
        if (idealSection) {
            idealSection.classList.toggle('disabled', disableIdeal);
            idealSection.querySelectorAll('input').forEach(function(inp) {
                inp.disabled = disableIdeal;
            });
        }
    }

    var splitToggle = document.getElementById('axis-split-toggle');
    if (splitToggle) {
        splitToggle.checked = splitMode;
        applySplitVisibility();
        applyIdealRangeAvailability();
        splitToggle.addEventListener('change', function() {
            if (splitToggle.checked) {
                axisCfg.right = JSON.parse(JSON.stringify(axisCfg.left));
                splitMode = true;
            } else {
                splitMode = false;
            }
            applySplitVisibility();
            applyIdealRangeAvailability();
            refreshControlActiveStates();
            refetchAll();
        });
    }

    // Y-Left / Y-Right tabs: show one axis's controls at a time in split mode
    // so the panel stays compact. Pure UI state — every control stays wired and
    // in the DOM whether or not its panel is visible.
    var axisTabs = document.querySelectorAll('.axis-tab');
    var axisPanels = document.querySelectorAll('.axis-tab-panel');
    axisTabs.forEach(function(tab) {
        tab.addEventListener('click', function() {
            var which = tab.dataset.axistab;
            axisTabs.forEach(function(t) {
                t.classList.toggle('active', t === tab);
            });
            axisPanels.forEach(function(p) {
                p.hidden = p.dataset.axispanel !== which;
            });
        });
    });

    refreshControlActiveStates();

    // --- Ideal range inputs ---
    var idealLoInput = document.getElementById('ideal-lo');
    var idealHiInput = document.getElementById('ideal-hi');
    var fertigationInput = document.getElementById('fertigation-overlay');
    var fertigationWarning = document.getElementById('fertigation-warning');
    if (idealLoInput && idealLo !== null) idealLoInput.value = idealLo;
    if (idealHiInput && idealHi !== null) idealHiInput.value = idealHi;
    if (fertigationInput) fertigationInput.checked = fertigationOverlay;
    function onIdealChange() {
        var v;
        if (idealLoInput) {
            v = parseFloat(idealLoInput.value);
            idealLo = Number.isFinite(v) ? v : null;
        }
        if (idealHiInput) {
            v = parseFloat(idealHiInput.value);
            idealHi = Number.isFinite(v) ? v : null;
        }
        updateIdealRange();
        syncUrl();
    }
    if (idealLoInput) idealLoInput.addEventListener('change', onIdealChange);
    if (idealHiInput) idealHiInput.addEventListener('change', onIdealChange);
    if (fertigationInput) {
        fertigationInput.addEventListener('change', function() {
            fertigationOverlay = fertigationInput.checked;
            if (fertigationOverlay && fertigationEvents.length === 0 && !fertigationLoadError) {
                syncUrl();
                fetchFertigationEvents();
                return;
            }
            updateIdealRange();
            updateFertigationWarning();
            syncUrl();
        });
    }

    function updateFertigationWarning() {
        if (!fertigationWarning) return;
        if (!fertigationOverlay) {
            fertigationWarning.style.display = 'none';
            fertigationWarning.textContent = '';
            return;
        }
        if (Object.keys(activeSeries).length === 0) {
            fertigationWarning.style.display = 'none';
            fertigationWarning.textContent = '';
            return;
        }
        function toMillis(iso) {
            if (!iso) return null;
            // JS Date.parse is reliably supported up to milliseconds; trim microseconds.
            var normalized = iso.replace(/\.(\d{3})\d+$/, '.$1');
            var ms = Date.parse(normalized);
            return Number.isFinite(ms) ? ms : null;
        }
        function currentWindow() {
            var lx = chartDiv.layout && chartDiv.layout.xaxis;
            var r = lx && lx.range;
            if (r && r.length === 2) {
                var a = toMillis(r[0]);
                var b = toMillis(r[1]);
                if (a !== null && b !== null) {
                    return { start: Math.min(a, b), end: Math.max(a, b) };
                }
            }
            var s = startDate ? toMillis(startDate + 'T00:00:00') : null;
            var e = endDate ? toMillis(endDate + 'T23:59:59') : null;
                return { start: Math.min(s, e), end: Math.max(s, e) };
            }
            var minT = null;
            var maxT = null;
            Object.keys(activeSeries).forEach(function(k) {
                var sd = seriesData[k];
                if (!sd || !sd.times || !sd.times.length) return;
                var first = toMillis(sd.times[0]);
                var last = toMillis(sd.times[sd.times.length - 1]);
                if (first === null || last === null) return;
                var lo = Math.min(first, last);
                var hi = Math.max(first, last);
                minT = minT === null ? lo : Math.min(minT, lo);
                maxT = maxT === null ? hi : Math.max(maxT, hi);
            });
            if (minT !== null && maxT !== null) {
                return { start: minT, end: maxT };
            }
            return null;
        }
        var viewWindow = currentWindow();
        var inView = 0;
        if (viewWindow) {
            fertigationEvents.forEach(function(t) {
                var ms = toMillis(t);
                if (ms !== null && ms >= viewWindow.start && ms <= viewWindow.end) {
                    inView += 1;
                }
            });
        }
        if (fertigationLoadError) {
            fertigationWarning.textContent = 'Failed to load fertigation events.';
            fertigationWarning.style.display = 'block';
            return;
        }
        if (fertigationTotalEvents > 0 && inView === 0) {
            var rangeTxt = (fertigationFirstDate && fertigationLastDate)
                ? (fertigationFirstDate + ' to ' + fertigationLastDate)
                : 'unknown range';
            fertigationWarning.textContent =
                'No fertigation events for the current view. '
                + 'Available fertigation dates: ' + rangeTxt + '.';
            fertigationWarning.style.display = 'block';
            return;
        }
        if (fertigationTotalEvents === 0) {
            fertigationWarning.textContent =
                'No fertigation events are available yet (CSV missing or empty).';
            fertigationWarning.style.display = 'block';
            return;
        }
        fertigationWarning.style.display = 'none';
        fertigationWarning.textContent = '';
    }

    function fetchFertigationEvents() {
        var url = '/api/fertigation-events';
        var qp = [];
        if (startDate) qp.push('start=' + encodeURIComponent(startDate));
        if (endDate) qp.push('end=' + encodeURIComponent(endDate));
        if (qp.length) url += '?' + qp.join('&');
        fetch(url)
            .then(function(r) {
                if (!r.ok) {
                    throw new Error('Failed to fetch fertigation events: HTTP ' + r.status);
                }
                return r.json();
            })
            .then(function(resp) {
                if (resp && resp.error) {
                    throw new Error(resp.error);
                }
                fertigationEvents = (resp.events || []).map(function(e) {
                    return e.time;
                });
                fertigationFirstDate = resp.first_date || null;
                fertigationLastDate = resp.last_date || null;
                fertigationTotalEvents = resp.total_events || 0;
                fertigationLoadError = false;
                updateIdealRange();
                updateFertigationWarning();
            })
            .catch(function() {
                fertigationEvents = [];
                fertigationFirstDate = null;
                fertigationLastDate = null;
                fertigationTotalEvents = 0;
                fertigationLoadError = true;
                updateIdealRange();
                updateFertigationWarning();
            });
    }
    if (fertigationOverlay) fetchFertigationEvents();

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
                    rebuildTraces();
                    updateStats();
                    updateY2();
                }
            });
        });
    }

    function sensorLabel(key, axis) {
        var s = allSensors.find(function(s) {
            return s.device + ':' + s.sensor === key;
        });
        if (!s) return key;
        var sm = s.sensor_meta || {};
        var dm = s.device_meta || {};
        var alias = sm.alias || s.sensor;
        var fmt = cfgFor(axis).labelFormat;

        if (fmt === 'raw') {
            return s.device + ' | ' + s.sensor;
        }
        var pos = dm.position || s.device;
        if (fmt === 'short') {
            return pos + ' \u2014 ' + alias;
        }
        // 'smart': position + alias + intention snippet
        var label = pos + ' \u2014 ' + alias;
        if (sm.intention) {
            var snippet = sm.intention.split(',')[0];
            if (snippet.length > 30) snippet = snippet.substring(0, 30) + '\u2026';
            label += ' (' + snippet + ')';
        }
        return label;
    }

    function anyAggregateEnabled() {
        return cfgFor('left').aggregateEnabled || cfgFor('right').aggregateEnabled;
    }

    function relabelAllTraces() {
        if (anyAggregateEnabled()) { rebuildTraces(); return; }
        var keys = Object.keys(activeSeries);
        if (keys.length === 0) return;
        keys.forEach(function(k) {
            var idx = activeSeries[k].traceIdx;
            var axis = activeSeries[k].axis;
            Plotly.restyle(chartDiv, { name: sensorLabel(k, axis) }, [idx]);
        });
    }

    // Colors are assigned by sorted-key index: unique within a chart, and
    // stable per key as long as the active-series set is unchanged.
    var TRACE_COLORS = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
        '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
        '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
        '#c49c94', '#f7b6d2', '#c7c7c7', '#dbdb8d', '#9edae5'
    ];
    function buildColorMap() {
        var sorted = Object.keys(activeSeries).slice().sort();
        var m = {};
        sorted.forEach(function(k, i) {
            m[k] = TRACE_COLORS[i % TRACE_COLORS.length];
        });
        return m;
    }

    // Translucent fill for the range band, derived from the series' own
    // palette colour (all TRACE_COLORS are #rrggbb).
    function hexToRgba(hex, alpha) {
        var r = parseInt(hex.slice(1, 3), 16);
        var g = parseInt(hex.slice(3, 5), 16);
        var b = parseInt(hex.slice(5, 7), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    // The band toggle is only meaningful for true ranges: it needs an active
    // aggregation, and SUM puts the line on a different scale than min/max.
    function bandAppliesTo(cfg) {
        return cfg.aggregateEnabled && cfg.aggregateFunc !== 'sum';
    }

    // Combine already-bucketed values from multiple series that share one
    // axis label. The server aligned every series to identical bucket
    // boundaries, so values at the same timestamp are directly combinable.
    // AVG must be count-weighted: a plain mean of per-series means is biased
    // when buckets hold unequal numbers of raw readings (e.g. a partial day).
    function combineAgg(values, counts, func) {
        if (values.length === 0) return null;
        if (func === 'max') return Math.max.apply(null, values);
        if (func === 'min') return Math.min.apply(null, values);
        if (func === 'sum') {
            var s = 0; values.forEach(function(v) { s += v; }); return s;
        }
        var num = 0, den = 0;  // avg, count-weighted
        for (var i = 0; i < values.length; i++) {
            num += values[i] * counts[i];
            den += counts[i];
        }
        return den > 0 ? num / den : null;
    }

    function formatBucket(mins) {
        if (mins === 0) return 'Off';
        if (mins < 60) return mins + ' min';
        if (mins === 60) return '1h';
        if (mins < 1440) {
            var h = mins / 60;
            return (mins % 60 ? h.toFixed(1) : h.toFixed(0)) + 'h';
        }
        if (mins === 1440) return '1 day';
        if (mins === 10080) return '1 week';
        if (mins === 20160) return '2 weeks';
        if (mins === 43200) return '1 month';
        return (mins / 1440) + ' days';
    }

    // Floor a local-ISO timestamp to its box-grouping bucket start. Boxes are
    // grouped entirely on the client (the server never buckets a box), so this
    // only needs to land on sensible local boundaries: sub-day widths floor
    // within the local day from midnight; day+ widths floor to whole local days.
    function floorBoxTime(iso, minutes) {
        if (!minutes || minutes <= 0) return iso;
        var m = iso.match(
            /^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2}):(\\d{2})([+-]\\d{2}:\\d{2}|Z)?/);
        if (!m) return iso;
        var Y = +m[1], Mo = +m[2], D = +m[3], H = +m[4], Mi = +m[5];
        var offset = m[7] && m[7] !== 'Z' ? m[7] : (m[7] === 'Z' ? 'Z' : '');
        function pad(n) { return (n < 10 ? '0' : '') + n; }
        if (minutes < 1440) {
            var since = H * 60 + Mi;
            var fl = Math.floor(since / minutes) * minutes;
            return Y + '-' + pad(Mo) + '-' + pad(D) + 'T'
                + pad(Math.floor(fl / 60)) + ':' + pad(fl % 60) + ':00' + offset;
        }
        var dayMs = 86400000;
        var stepDays = Math.round(minutes / 1440);
        var dayNum = Math.floor(Date.UTC(Y, Mo - 1, D) / dayMs);
        var dt = new Date(Math.floor(dayNum / stepDays) * stepDays * dayMs);
        return dt.getUTCFullYear() + '-' + pad(dt.getUTCMonth() + 1) + '-'
            + pad(dt.getUTCDate()) + 'T00:00:00' + offset;
    }

    function rebuildTraces() {
        // Clear all Plotly traces
        var traceCount = chartDiv.data ? chartDiv.data.length : 0;
        if (traceCount > 0) {
            var indices = [];
            for (var i = 0; i < traceCount; i++) indices.push(i);
            Plotly.deleteTraces(chartDiv, indices);
        }

        var keys = Object.keys(activeSeries);
        if (keys.length === 0) return;

        var colorMap = buildColorMap();

        // Partition keys by axis so each side can use its own config
        var keysByAxis = { left: [], right: [] };
        keys.forEach(function(k) {
            var axis = activeSeries[k].axis;
            keysByAxis[axis].push(k);
        });

        var traces = [];
        var traceIdxMap = {};

        ['left', 'right'].forEach(function(axis) {
            var axisKeys = keysByAxis[axis];
            if (axisKeys.length === 0) return;
            var cfg = cfgFor(axis);

            if (cfg.chartType === 'box') {
                // One box-series per sensor (no same-label pooling). Each raw
                // point is floored to its box-width bucket so Plotly groups the
                // distribution and computes the quartiles; boxmode:'group' sits
                // same-bucket sensors side-by-side on the shared time axis.
                axisKeys.forEach(function(k) {
                    var sd = seriesData[k];
                    if (!sd) return;
                    var color = colorMap[k];
                    var bx = sd.times.map(function(t) {
                        return floorBoxTime(t, cfg.bucketMinutes);
                    });
                    traceIdxMap[k] = traces.length;
                    traces.push({
                        type: 'box',
                        x: bx, y: sd.values,
                        name: sensorLabel(k, axis),
                        yaxis: axis === 'right' ? 'y2' : 'y',
                        marker: {color: color},
                        line: {color: color}
                    });
                });
                return;
            }

            // Render-mode seam: scatter draws the same points as markers.
            var traceMode = cfg.chartType === 'scatter' ? 'markers' : 'lines';

            if (!cfg.aggregateEnabled) {
                axisKeys.forEach(function(k) {
                    var sd = seriesData[k];
                    if (!sd) return;
                    var color = colorMap[k];
                    var trace = {
                        x: sd.times, y: sd.values,
                        name: sensorLabel(k, axis),
                        mode: traceMode,
                        yaxis: axis === 'right' ? 'y2' : 'y',
                        line: {color: color},
                        marker: {color: color}
                    };
                    if (axis === 'right') { trace.line.dash = 'dash'; }
                    traceIdxMap[k] = traces.length;
                    traces.push(trace);
                });
            } else {
                var groups = {};
                axisKeys.forEach(function(k) {
                    var sd = seriesData[k];
                    if (!sd) return;
                    var label = sensorLabel(k, axis);
                    if (!groups[label]) {
                        groups[label] = { label: label, series: [], firstKey: k };
                    } else if (k < groups[label].firstKey) {
                        groups[label].firstKey = k;
                    }
                    groups[label].series.push(sd);
                });
                Object.keys(groups).forEach(function(label) {
                    var g = groups[label];
                    var merged;
                    if (g.series.length === 1) {
                        // Server already bucketed+aggregated this series.
                        var s0 = g.series[0];
                        merged = {
                            times: s0.times, values: s0.values,
                            mins: s0.mins, maxs: s0.maxs
                        };
                    } else {
                        // Series share a label: recombine on the identical
                        // server-side bucket timestamps, count-weighting AVG.
                        // The band spans all series, so min-of-mins/max-of-maxs.
                        var bmap = {};
                        g.series.forEach(function(sd) {
                            sd.times.forEach(function(t, i) {
                                var v = sd.values[i];
                                if (v === null || v === undefined) return;
                                if (!bmap[t]) bmap[t] = {
                                    vals: [], counts: [], mins: [], maxs: [] };
                                bmap[t].vals.push(v);
                                bmap[t].counts.push(sd.counts ? sd.counts[i] : 1);
                                if (sd.mins && sd.mins[i] != null) bmap[t].mins.push(sd.mins[i]);
                                if (sd.maxs && sd.maxs[i] != null) bmap[t].maxs.push(sd.maxs[i]);
                            });
                        });
                        var sortedTimes = Object.keys(bmap).sort();
                        var aggValues = sortedTimes.map(function(t) {
                            return combineAgg(
                                bmap[t].vals, bmap[t].counts, cfg.aggregateFunc);
                        });
                        var aggMins = sortedTimes.map(function(t) {
                            return bmap[t].mins.length
                                ? Math.min.apply(null, bmap[t].mins) : null; });
                        var aggMaxs = sortedTimes.map(function(t) {
                            return bmap[t].maxs.length
                                ? Math.max.apply(null, bmap[t].maxs) : null; });
                        merged = {
                            times: sortedTimes, values: aggValues,
                            mins: aggMins, maxs: aggMaxs
                        };
                    }

                    var suffix = g.series.length > 1
                    ? ' [' + cfg.aggregateFunc.toUpperCase() + '\u00d7' + g.series.length + ']'
                    : '';
                var color = colorMap[g.firstKey];
                var yaxisName = axis === 'right' ? 'y2' : 'y';

                // Range band: a translucent min->max area drawn *before* the
                // line so the line sits on top. Two zero-width traces (lower
                // then upper-with-fill) make Plotly shade between them.
                var bandShown = cfg.bandEnabled && bandAppliesTo(cfg)
                    && merged.mins && merged.maxs;
                if (bandShown) {
                    traces.push({
                        x: merged.times, y: merged.mins,
                        mode: 'lines', line: {width: 0},
                        yaxis: yaxisName,
                        hoverinfo: 'skip', showlegend: false
                    });
                    traces.push({
                        x: merged.times, y: merged.maxs,
                        mode: 'lines', line: {width: 0},
                        fill: 'tonexty', fillcolor: hexToRgba(color, 0.18),
                        yaxis: yaxisName,
                        hoverinfo: 'skip', showlegend: false
                    });
                }

                var trace = {
                    x: merged.times, y: merged.values,
                    name: g.label + suffix,
                    mode: traceMode,
                    yaxis: yaxisName,
                    line: {color: color},
                    marker: {color: color}
                };
                if (axis === 'right') { trace.line.dash = 'dash'; }
                // When the band is on, surface its exact extremes in the
                // (x-unified) tooltip so the shaded area is readable as numbers.
                // Name goes in the template (matches the monitor charts) so it
                // stays visible alongside <extra></extra>.
                if (bandShown) {
                    trace.customdata = merged.times.map(function(_, i) {
                        return [merged.mins[i], merged.maxs[i]];
                    });
                    trace.hovertemplate = '<b>' + (g.label + suffix) + '</b><br>'
                        + cfg.aggregateFunc + ' %{y:.2f}'
                        + '  ·  range %{customdata[0]:.2f}–%{customdata[1]:.2f}'
                        + '<extra></extra>';
                }
                traces.push(trace);
                });
            }
        });

        if (traces.length > 0) Plotly.addTraces(chartDiv, traces);

        keys.forEach(function(k) {
            var axis = activeSeries[k].axis;
            var acfg = cfgFor(axis);
            // Box draws one trace per key (like the non-aggregated path), so it
            // keeps a real trace index even though aggregation may be enabled.
            if (acfg.chartType !== 'box' && acfg.aggregateEnabled) {
                activeSeries[k].traceIdx = -1;
            } else {
                activeSeries[k].traceIdx = traceIdxMap[k] != null ? traceIdxMap[k] : -1;
            }
        });
        // 'x unified' hover collects every trace at an x, which on grouped
        // boxplots pulls neighbouring boxes into one tooltip. Switch to
        // 'closest' so each box hovers alone; keep unified for line/scatter.
        var anyBox = ['left', 'right'].some(function(axis) {
            return keysByAxis[axis].length && cfgFor(axis).chartType === 'box';
        });
        Plotly.relayout(chartDiv, {hovermode: anyBox ? 'closest' : 'x unified'});
        updateIdealRange();
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
        var acfg = cfgFor(axis);
        // Boxplots build their distribution from raw points on the client, so
        // they always fetch raw (the agg func is ignored — the slider only
        // sets the client-side box-grouping width).
        if (acfg.chartType !== 'box'
            && acfg.aggregateEnabled && acfg.bucketMinutes > 0) {
            url += '&bkt=' + acfg.bucketMinutes
                 + '&agg=' + encodeURIComponent(acfg.aggregateFunc);
        }

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                var data = resp.data || [];
                if (data.length === 0) { if (cb) cb(); return; }

                var times = data.map(function(d) { return d.time; });
                var values = data.map(function(d) { return d.value; });
                var counts = data.map(function(d) {
                    return d.count != null ? d.count : 1; });
                // min/max ride along only on bucketed responses (range band).
                var mins = data.map(function(d) {
                    return d.min != null ? d.min : null; });
                var maxs = data.map(function(d) {
                    return d.max != null ? d.max : null; });

                seriesData[key] = {
                    times: times, values: values, counts: counts,
                    mins: mins, maxs: maxs
                };
                activeSeries[key] = {
                    axis: axis, traceIdx: -1, points: data.length,
                    truncated: !!resp.truncated,
                    limit: resp.limit || 0
                };
                totalPoints += data.length;
                showEmpty(false);
                if (cb) cb();
            });
    }

    // Re-fetch every active series with the current per-axis aggregation
    // config, then rebuild. Used whenever agg / bucket / split changes: the
    // client no longer caches raw rows to recompute from (server-side agg),
    // so a tiny refetch replaces the old free local recompute.
    function refetchAll() {
        var keys = Object.keys(activeSeries);
        if (keys.length === 0) { rebuildTraces(); syncUrl(); return; }
        var specs = keys.map(function(k) {
            return { key: k, axis: activeSeries[k].axis }; });
        totalPoints = 0;
        var done = 0;
        specs.forEach(function(s) {
            fetchAndAdd(s.key, s.axis, function() {
                done++;
                if (done === specs.length) {
                    rebuildTraces();
                    syncUrl();
                    updateStats();
                    updateY2();
                }
            });
        });
    }

    function addOrUpdateSeries(key, axis) {
        if (activeSeries[key]) {
            // Already loaded. The cached series was fetched for the old
            // axis; under split mode the new axis may have a different agg
            // config, so refetch this one key (tiny payload).
            totalPoints -= activeSeries[key].points || 0;
            activeSeries[key].axis = axis;
            fetchAndAdd(key, axis, function() {
                rebuildTraces();
                syncUrl();
                updateStats();
                updateY2();
            });
        } else {
            // Need to fetch — syncUrl after fetch completes
            showEmpty(false);
            fetchAndAdd(key, axis, function() {
                rebuildTraces();
                syncUrl();
                updateStats();
                updateY2();
            });
        }
    }

    function removeSeries(key) {
        if (!activeSeries[key]) return;
        totalPoints -= activeSeries[key].points || 0;
        delete activeSeries[key];
        delete seriesData[key];
        rebuildTraces();
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
        applyIdealRangeAvailability();
        relayoutUpdate['yaxis.title.text'] = leftKeys.length === 1
            ? leftKeys[0] : '';
        relayoutUpdate['yaxis2.title.text'] = rightKeys.length === 1
            ? rightKeys[0] : '';
        Plotly.relayout(chartDiv, relayoutUpdate);
    }

    function updateIdealRange() {
        var shapes = [];
        // Ideal range is ambiguous with active dual Y axes; keep stored values but
        // suppress only ideal-range visuals, not other overlays.
        if (!hasDualAxesActive()) {
            var yref = idealRangeAxisRef();
            var lo = idealLo;
            var hi = idealHi;
            if (lo !== null && hi !== null && lo < hi) {
                shapes.push({
                    type: 'rect',
                    x0: 0, x1: 1, xref: 'paper',
                    yref: yref,
                    y0: lo, y1: hi,
                    fillcolor: 'rgba(34, 197, 94, 0.12)',
                    line: { width: 0 },
                    layer: 'below'
                });
            } else {
                var lineVal = lo !== null ? lo : hi;
                if (lineVal !== null) {
                    shapes.push({
                        type: 'line',
                        x0: 0, x1: 1, xref: 'paper',
                        yref: yref,
                        y0: lineVal, y1: lineVal,
                        line: { color: 'rgba(34, 197, 94, 0.85)', width: 1.5, dash: 'dash' }
                    });
                }
            }
        }

        if (fertigationOverlay && fertigationEvents.length) {
            fertigationEvents.forEach(function(t) {
                shapes.push({
                    type: 'line',
                    xref: 'x',
                    x0: t,
                    x1: t,
                    yref: 'paper',
                    y0: 0,
                    y1: 1,
                    line: { color: 'rgba(14, 165, 233, 0.9)', width: 1, dash: 'dot' },
                    layer: 'above'
                });
            });
        }

        Plotly.relayout(chartDiv, { shapes: shapes });
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
        var L = axisCfg.left;
        if (L.labelFormat !== 'smart') p.set('lbl', L.labelFormat);
        else p.delete('lbl');
        if (L.chartType !== 'line') p.set('ct', L.chartType);
        else p.delete('ct');
        if (L.aggregateEnabled) p.set('agg', L.aggregateFunc);
        else p.delete('agg');
        if ((L.aggregateEnabled || L.chartType === 'box') && L.bucketMinutes !== 10) {
            p.set('bkt', L.bucketMinutes);
        } else p.delete('bkt');
        if (L.bandEnabled) p.set('band', '1');
        else p.delete('band');
        if (splitMode) {
            p.set('split', '1');
            var R = axisCfg.right;
            if (R.labelFormat !== L.labelFormat) p.set('lbl_r', R.labelFormat);
            else p.delete('lbl_r');
            if (R.chartType !== L.chartType) p.set('ct_r', R.chartType);
            else p.delete('ct_r');
            if (R.aggregateEnabled !== L.aggregateEnabled
                || (R.aggregateEnabled && R.aggregateFunc !== L.aggregateFunc)) {
                p.set('agg_r', R.aggregateEnabled ? R.aggregateFunc : 'off');
            } else {
                p.delete('agg_r');
            }
            if ((R.aggregateEnabled || R.chartType === 'box')
                && R.bucketMinutes !== L.bucketMinutes) {
                p.set('bkt_r', R.bucketMinutes);
            } else {
                p.delete('bkt_r');
            }
            // Right inherits left's band on load, so only emit band_r when it
            // differs (explicit '0' overrides an inherited-on state).
            if (R.bandEnabled !== L.bandEnabled) p.set('band_r', R.bandEnabled ? '1' : '0');
            else p.delete('band_r');
        } else {
            p.delete('split');
            p.delete('lbl_r');
            p.delete('ct_r');
            p.delete('agg_r');
            p.delete('bkt_r');
            p.delete('band_r');
        }
        if (idealLo !== null) p.set('ideal_lo', idealLo);
        else p.delete('ideal_lo');
        if (idealHi !== null) p.set('ideal_hi', idealHi);
        else p.delete('ideal_hi');
        if (fertigationOverlay) p.set('fert_events', '1');
        else p.delete('fert_events');
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
        ['s', 'r', 'lbl', 'ct', 'agg', 'bkt', 'band',
         'split', 'lbl_r', 'ct_r', 'agg_r', 'bkt_r', 'band_r',
            'ideal_lo', 'ideal_hi', 'fert_events'].forEach(function(name) {
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
        ['s', 'r', 'lbl', 'ct', 'agg', 'bkt', 'band',
         'split', 'lbl_r', 'ct_r', 'agg_r', 'bkt_r', 'band_r',
         'ideal_lo', 'ideal_hi', 'fert_events'].forEach(function(name) {
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
        ['lbl', 'agg', 'bkt', 'band',
         'split', 'lbl_r', 'agg_r', 'bkt_r', 'band_r',
         'ideal_lo', 'ideal_hi', 'fert_events'].forEach(function(k) {
            if (chart[k]) params.set(k, chart[k]);
        });
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
            lbl: params.get('lbl') || '',
            agg: params.get('agg') || '',
            bkt: params.get('bkt') || '',
            band: params.get('band') || '',
            split: params.get('split') || '',
            lbl_r: params.get('lbl_r') || '',
            agg_r: params.get('agg_r') || '',
            bkt_r: params.get('bkt_r') || '',
            band_r: params.get('band_r') || '',
            ideal_lo: params.get('ideal_lo') || '',
            ideal_hi: params.get('ideal_hi') || '',
            fert_events: params.get('fert_events') || '',
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



def _render_source_indicator(active_source: str | None) -> str:
    """Render a data-source indicator in the nav bar.

    Single source: static badge. Multiple sources: interactive dropdown.
    """
    if not _data_sources:
        return ""
    icon = '<span style="font-size:0.9rem;opacity:0.6">\u26c1</span>'
    if len(_data_sources) == 1:
        label = _data_sources[0].label
        return (
            f'<span title="Data source: {label}"'
            f' style="display:flex;align-items:center;gap:0.3rem;cursor:default">'
            f"{icon}"
            f'<span style="font-size:0.75rem;opacity:0.7">{label}</span>'
            f"</span>"
        )
    options = "".join(
        f'<option value="{ds.key}"{" selected" if ds.key == active_source else ""}>'
        f"{ds.label}</option>"
        for ds in _data_sources
    )
    return (
        f'<span title="Data source"'
        f' style="display:flex;align-items:center;gap:0.3rem">'
        f"{icon}"
        f'<select id="source-toggle" onchange="switchSource(this.value)"'
        f' style="width:auto;margin:0;padding:0.2rem 0.5rem;font-size:0.8rem">'
        f"{options}</select></span>"
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
    source_html = _render_source_indicator(data_source)

    groups = [
        '<div class="nav-group">'
        '<a href="/">Home</a>'
        '<a href="/dashboard">Dashboard</a>'
        '<a href="/chart">Chart</a>'
        "</div>",
    ]
    if source_html:
        groups.append(f'<div class="nav-group">{source_html}</div>')
    if user:
        groups.append(
            f'<div class="nav-group">'
            f'<span class="nav-user">{user} | <a href="/auth/logout">Logout</a></span>'
            f"</div>",
        )
    groups.append(
        '<div class="nav-group">'
        '<button id="theme-toggle" title="Toggle dark mode">'
        '<span class="icon-sun">&#9788;</span>'
        '<span class="icon-moon">&#9790;</span>'
        "</button></div>",
    )

    return f"""
    <nav class="dashboard-nav">
        <a href="/" class="brand">{name}</a>
        <div class="nav-links">
            {"".join(groups)}
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
        <script>{EXPLORE_TABS_JS}</script>
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

    # Subtle inline glyphs for the chart-type toggle. ``currentColor`` lets each
    # icon track the button's text colour (incl. the white active state).
    ct_icon_line = (
        '<svg class="ct-icon" viewBox="0 0 12 12" aria-hidden="true">'
        '<polyline points="1,9 4,5 7,7 11,2" fill="none" stroke="currentColor" '
        'stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )
    ct_icon_scatter = (
        '<svg class="ct-icon" viewBox="0 0 12 12" aria-hidden="true">'
        '<circle cx="2.5" cy="8.5" r="1.1" fill="currentColor"/>'
        '<circle cx="6" cy="5" r="1.1" fill="currentColor"/>'
        '<circle cx="9.5" cy="6.5" r="1.1" fill="currentColor"/>'
        '<circle cx="8" cy="2.5" r="1.1" fill="currentColor"/></svg>'
    )
    ct_icon_box = (
        '<svg class="ct-icon" viewBox="0 0 12 12" aria-hidden="true">'
        '<line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" stroke-width="1.1"/>'
        '<rect x="3" y="4" width="6" height="4.5" fill="none" stroke="currentColor" '
        'stroke-width="1.1"/>'
        '<line x1="3" y1="6.2" x2="9" y2="6.2" stroke="currentColor" stroke-width="1.1"/></svg>'
    )

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
            <label class="axis-split-toggle">
                <input type="checkbox" id="axis-split-toggle">
                Configure axes separately
            </label>
            <div id="axis-controls-unified">
                <small>Chart type</small>
                <div class="group-toggle">
                    <button class="ct-btn" data-ct="line" data-axis="left"
                        >{ct_icon_line}Line</button>
                    <button class="ct-btn" data-ct="scatter" data-axis="left"
                        >{ct_icon_scatter}Scatter</button>
                    <button class="ct-btn" data-ct="box" data-axis="left"
                        >{ct_icon_box}Box</button>
                </div>
                <h4>Labels</h4>
                <div class="group-toggle">
                    <button class="label-btn" data-label="smart" data-axis="left"
                        >Smart</button>
                    <button class="label-btn" data-label="short" data-axis="left"
                        >Short</button>
                    <button class="label-btn" data-label="raw" data-axis="left"
                        >Raw ID</button>
                </div>
                <small>Aggregate matching labels</small>
                <div class="group-toggle">
                    <button class="agg-btn" data-agg="off" data-axis="left">OFF</button>
                    <button class="agg-btn" data-agg="avg" data-axis="left">AVG</button>
                    <button class="agg-btn" data-agg="max" data-axis="left">MAX</button>
                    <button class="agg-btn" data-agg="min" data-axis="left">MIN</button>
                    <button class="agg-btn" data-agg="sum" data-axis="left">SUM</button>
                </div>
                <div class="bucket-slider">
                    <label><span class="bucket-prefix" data-axis="left">Bucket:</span>
                        <span class="bucket-label" data-axis="left">10 min</span></label>
                    <input type="range" class="bucket-slider-input" data-axis="left"
                        min="0" max="13" value="3" step="1">
                </div>
                <label class="band-toggle">
                    <input type="checkbox" class="band-input" data-axis="left">
                    Range band
                </label>
                <small class="band-hint">shade lowest–highest in each bucket</small>
            </div>
            <div id="axis-controls-split" style="display:none;">
                <div class="axis-tabs" role="tablist">
                    <button class="axis-tab active" data-axistab="left"
                        role="tab">Y-Left</button>
                    <button class="axis-tab" data-axistab="right"
                        role="tab">Y-Right</button>
                </div>
                <div class="axis-tab-panel" data-axispanel="left">
                <small>Chart type</small>
                <div class="group-toggle">
                    <button class="ct-btn" data-ct="line" data-axis="left"
                        >{ct_icon_line}Line</button>
                    <button class="ct-btn" data-ct="scatter" data-axis="left"
                        >{ct_icon_scatter}Scatter</button>
                    <button class="ct-btn" data-ct="box" data-axis="left"
                        >{ct_icon_box}Box</button>
                </div>
                <small>Labels</small>
                <div class="group-toggle">
                    <button class="label-btn" data-label="smart" data-axis="left"
                        >Smart</button>
                    <button class="label-btn" data-label="short" data-axis="left"
                        >Short</button>
                    <button class="label-btn" data-label="raw" data-axis="left"
                        >Raw ID</button>
                </div>
                <small>Aggregate matching labels</small>
                <div class="group-toggle">
                    <button class="agg-btn" data-agg="off" data-axis="left">OFF</button>
                    <button class="agg-btn" data-agg="avg" data-axis="left">AVG</button>
                    <button class="agg-btn" data-agg="max" data-axis="left">MAX</button>
                    <button class="agg-btn" data-agg="min" data-axis="left">MIN</button>
                    <button class="agg-btn" data-agg="sum" data-axis="left">SUM</button>
                </div>
                <div class="bucket-slider">
                    <label><span class="bucket-prefix" data-axis="left">Bucket:</span>
                        <span class="bucket-label" data-axis="left">10 min</span></label>
                    <input type="range" class="bucket-slider-input" data-axis="left"
                        min="0" max="13" value="3" step="1">
                </div>
                <label class="band-toggle">
                    <input type="checkbox" class="band-input" data-axis="left">
                    Range band
                </label>
                <small class="band-hint">shade lowest–highest in each bucket</small>
                </div>
                <div class="axis-tab-panel" data-axispanel="right" hidden>
                <small>Chart type</small>
                <div class="group-toggle">
                    <button class="ct-btn" data-ct="line" data-axis="right"
                        >{ct_icon_line}Line</button>
                    <button class="ct-btn" data-ct="scatter" data-axis="right"
                        >{ct_icon_scatter}Scatter</button>
                    <button class="ct-btn" data-ct="box" data-axis="right"
                        >{ct_icon_box}Box</button>
                </div>
                <small>Labels</small>
                <div class="group-toggle">
                    <button class="label-btn" data-label="smart" data-axis="right"
                        >Smart</button>
                    <button class="label-btn" data-label="short" data-axis="right"
                        >Short</button>
                    <button class="label-btn" data-label="raw" data-axis="right"
                        >Raw ID</button>
                </div>
                <small>Aggregate matching labels</small>
                <div class="group-toggle">
                    <button class="agg-btn" data-agg="off" data-axis="right">OFF</button>
                    <button class="agg-btn" data-agg="avg" data-axis="right">AVG</button>
                    <button class="agg-btn" data-agg="max" data-axis="right">MAX</button>
                    <button class="agg-btn" data-agg="min" data-axis="right">MIN</button>
                    <button class="agg-btn" data-agg="sum" data-axis="right">SUM</button>
                </div>
                <div class="bucket-slider">
                    <label><span class="bucket-prefix" data-axis="right">Bucket:</span>
                        <span class="bucket-label" data-axis="right">10 min</span>
                    </label>
                    <input type="range" class="bucket-slider-input" data-axis="right"
                        min="0" max="13" value="3" step="1">
                </div>
                <label class="band-toggle">
                    <input type="checkbox" class="band-input" data-axis="right">
                    Range band
                </label>
                <small class="band-hint">shade lowest–highest in each bucket</small>
                </div>
            </div>
            <details class="advanced-options" id="advanced-options">
                <summary>Advanced options</summary>
                <div class="advanced-inner">
                    <div class="ideal-range-section" id="ideal-range-section">
                        <h4>Ideal range</h4>
                        <div class="ideal-range-inputs">
                            <input type="number" id="ideal-lo" class="ideal-input"
                                   aria-label="Ideal minimum"
                                   step="any" placeholder="Min">
                            <span class="date-sep">&ndash;</span>
                            <input type="number" id="ideal-hi" class="ideal-input"
                                   aria-label="Ideal maximum"
                                   step="any" placeholder="Max">
                        </div>
                        <small>Horizontal reference line/band (Y-axis)</small>
                    </div>
                    <label class="advanced-toggle">
                        <input type="checkbox" id="fertigation-overlay">
                        Event overlay (fertigation)
                    </label>
                </div>
            </details>
        </div>
        <div class="chart-main">
            <button class="panel-toggle outline" id="panel-toggle">
                Hide controls</button>
            <button class="panel-toggle outline" id="save-to-dashboard"
                title="Save current chart view to dashboard">&#9734; Save</button>
            <div class="chart-stats" id="chart-stats"></div>
            <div class="chart-warning" id="fertigation-warning" style="display:none"></div>
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
