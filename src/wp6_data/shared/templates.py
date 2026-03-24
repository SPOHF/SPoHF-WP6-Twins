"""Shared HTML templates for WP6 dashboards."""

from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta

_dashboard_id = "blue"
_current_user: ContextVar[str | None] = ContextVar("_current_user", default=None)


def configure_dashboard(dashboard_id: str) -> None:
    """Set the dashboard identity (blue/red) for styling. Call once at startup."""
    global _dashboard_id
    _dashboard_id = dashboard_id


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


def render_card(title: str, body: str, *, description: str = "") -> str:
    """Render content wrapped in a styled article card."""
    desc = f"<p>{description}</p>" if description else ""
    return f"<article><h2>{title}</h2>{desc}{body}</article>"


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render an HTML table from headers and row data (cells may contain HTML)."""
    thead = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
    tbody = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>"


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

    /* --- Dashboard identity: Blue --- */
    [data-dashboard="blue"] {
        --dashboard-primary: #2563eb;
        --dashboard-primary-light: #3b82f6;
        --dashboard-primary-dark: #1d4ed8;
        --dashboard-accent: #0ea5e9;
        --dashboard-gradient-start: #2563eb;
        --dashboard-gradient-end: #0ea5e9;
        --dashboard-surface: rgba(37, 99, 235, 0.04);
        --dashboard-surface-hover: rgba(37, 99, 235, 0.08);
    }
    /* --- Dashboard identity: Red --- */
    [data-dashboard="red"] {
        --dashboard-primary: #dc2626;
        --dashboard-primary-light: #ef4444;
        --dashboard-primary-dark: #b91c1c;
        --dashboard-accent: #f97316;
        --dashboard-gradient-start: #dc2626;
        --dashboard-gradient-end: #f97316;
        --dashboard-surface: rgba(220, 38, 38, 0.04);
        --dashboard-surface-hover: rgba(220, 38, 38, 0.08);
    }
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
    [data-theme="dark"][data-dashboard="blue"] {
        --dashboard-surface: rgba(37, 99, 235, 0.08);
        --dashboard-surface-hover: rgba(37, 99, 235, 0.14);
    }
    [data-theme="dark"][data-dashboard="red"] {
        --dashboard-surface: rgba(220, 38, 38, 0.08);
        --dashboard-surface-hover: rgba(220, 38, 38, 0.14);
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
        padding: 1rem; border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    article:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1), 0 2px 4px rgba(0,0,0,0.06);
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
    .stats-grid article:hover { transform: translateY(-2px); }
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
    thead {
        background: var(--dashboard-primary);
        color: #fff;
    }
    thead th { color: #fff; --pico-color: #fff; border-color: var(--dashboard-primary); }
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

SOURCE_TOGGLE_JS = """
    function switchSource(value) {
        document.cookie = 'wp6_blue_source=' + value + ';path=/;max-age=31536000';
        location.reload();
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

    // Fetch sensor list and build tree
    var allSensors = [];
    var currentGrouping = 'measurement';
    fetch('/api/sensors')
        .then(function(r) { return r.json(); })
        .then(function(sensors) {
            allSensors = sensors;
            buildTree(sensors, currentGrouping);
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
        // Group sensors into {groupKey: [{device, sensor}, ...]}
        var groups = {};
        sensors.forEach(function(s) {
            var key = groupBy === 'device' ? s.device : s.sensor;
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
                var label = groupBy === 'device'
                    ? s.sensor : s.device;
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
                    + key + '">' + label + '</span>';
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
                    name: key,
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
        Plotly.relayout(chartDiv, {
            'yaxis2.visible': hasY2,
            'yaxis2.showticklabels': hasY2
        });
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

_DASHBOARD_NAMES = {"blue": "SPoHF Blue", "red": "SPoHF Red"}


def _render_source_toggle(data_source: str) -> str:
    """Render a data-source <select> dropdown for the nav bar."""
    from wp6_data.blue.datasource import SOURCE_LABELS, SOURCES

    options = "".join(
        f'<option value="{key}"{" selected" if key == data_source else ""}>'
        f"{label}</option>"
        for key, label in SOURCE_LABELS.items()
        if key in SOURCES
    )
    return (
        f'<select id="source-toggle" onchange="switchSource(this.value)"'
        f' style="width:auto;margin:0;padding:0.2rem 0.5rem;font-size:0.8rem">'
        f"{options}</select>"
    )


def render_nav_bar(*, data_source: str | None = None) -> str:
    """Render a sticky nav bar with dashboard name, home link, and dark mode toggle."""
    name = _DASHBOARD_NAMES.get(_dashboard_id, "SPoHF")
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
        f'<div class="back"><a href="{back_url}">&larr; Back to Dashboard</a></div>'
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
        <script>{SOURCE_TOGGLE_JS}</script>
    </body>
    </html>
    """


def render_unified_chart_page(
    title: str,
    start: date,
    end: date,
    *,
    data_source: str | None = None,
) -> str:
    """Render the unified chart page with side panel and on-demand data loading.

    The page starts empty; client-side JS fetches sensor list and series data.
    URL params ``s`` and ``r`` encode the selected series for bookmarking.

    Args:
        title: Page title.
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
                    >By metric</button>
                <button class="group-btn" data-group="device"
                    >By device</button>
            </div>
            <div id="sensor-panel">Loading sensors...</div>
        </div>
        <div class="chart-main">
            <button class="panel-toggle outline" id="panel-toggle">
                Hide controls</button>
            <div class="chart-stats" id="chart-stats"></div>
            <div class="chart-empty" id="chart-empty">
                Select sensors from the panel to start charting</div>
            <div id="chart-area"></div>
        </div>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>{UNIFIED_CHART_JS}</script>
    """

    return render_page(
        title,
        content,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
        data_source=data_source,
    )
