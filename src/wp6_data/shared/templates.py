"""Shared HTML templates for WP6 dashboards."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

_dashboard_id = "blue"


def configure_dashboard(dashboard_id: str) -> None:
    """Set the dashboard identity (blue/red) for styling. Call once at startup."""
    global _dashboard_id
    _dashboard_id = dashboard_id


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
            <label>From <input type="date" id="df-start" name="start"
                   value="{start.isoformat()}"></label>
            <label>To <input type="date" id="df-end" name="end"
                   value="{end.isoformat()}"></label>
            <button type="submit" class="outline">Apply</button>
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


def render_compare_form(
    device_data: dict[str, list[str]],
    action_url: str = "/compare/chart",
) -> str:
    """Render a dual-axis compare form with cascading device → measurement selects.

    Args:
        device_data: Mapping of selectable entity (e.g. device id) to its
            available sub-options (e.g. measurements or sensor tags).
            Must be JSON-serialisable.
        action_url: Form action URL.

    Returns:
        HTML string containing the form, fieldsets, and JavaScript.
    """
    import json

    device_data_json = json.dumps(dict(sorted(device_data.items())))
    device_ids = sorted(device_data.keys())

    def _select_html(prefix: str, label: str, *, optional: bool = False) -> str:
        none_option = '<option value="">— None —</option>' if optional else ""
        device_options = "".join(f'<option value="{d}">{d}</option>' for d in device_ids)
        return f"""
        <fieldset>
            <legend><strong>{label}</strong></legend>
            <div class="compare-selects">
                <label>Device
                    <select name="{prefix}_device" id="{prefix}_device"
                            onchange="updateMeasurements('{prefix}')">
                        {none_option}{device_options}
                    </select>
                </label>
                <label>Measurement
                    <select name="{prefix}_measurement" id="{prefix}_measurement">
                    </select>
                </label>
            </div>
        </fieldset>
        """

    return f"""
        <form method="get" action="{action_url}">
            <div class="compare-axes">
                {_select_html("left", "Left Y-axis")}
                {_select_html("right", "Right Y-axis", optional=True)}
            </div>
            <button type="submit">Generate Chart</button>
        </form>
        <script>
        var deviceData = {device_data_json};
        function updateMeasurements(prefix) {{
            var device = document.getElementById(prefix + '_device').value;
            var sel = document.getElementById(prefix + '_measurement');
            sel.innerHTML = '';
            if (!device) return;
            (deviceData[device] || []).forEach(function(m) {{
                var opt = document.createElement('option');
                opt.value = m; opt.textContent = m;
                sel.appendChild(opt);
            }});
        }}
        updateMeasurements('left');
        updateMeasurements('right');
        </script>
    """


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

    /* --- Compare form --- */
    .compare-axes { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
    .compare-selects { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .compare-selects label { margin-bottom: 0; }

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

_DASHBOARD_NAMES = {"blue": "SPoHF Blue", "red": "SPoHF Red"}


def render_nav_bar() -> str:
    """Render a sticky nav bar with dashboard name, home link, and dark mode toggle."""
    name = _DASHBOARD_NAMES.get(_dashboard_id, "SPoHF")
    return f"""
    <nav class="dashboard-nav">
        <a href="/" class="brand">{name}</a>
        <div class="nav-links">
            <a href="/">Home</a>
            <a href="/compare">Compare</a>
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
        {render_nav_bar()}
        <main>
            {back_html}
            {content}
            {footer_html}
        </main>
        <script>{TOGGLE_JS}</script>
    </body>
    </html>
    """


def render_chart_page(
    df: pd.DataFrame,
    fig: go.Figure,
    title: str,
    start: date,
    end: date,
    *,
    back_url: str = "/",
    extra_params: dict[str, str] | None = None,
    extra_css: str = "",
) -> str:
    """Render a full chart page with date filter, empty-data fallback, stats, and layout.

    Callers build their own ``fig`` (chart logic differs per dashboard), but pass
    ``df`` so this helper can check emptiness and compute a data-point count.

    Args:
        df: DataFrame used to check emptiness and compute stats.
        fig: Plotly Figure to render (ignored when *df* is empty).
        title: Page ``<title>`` passed to :func:`render_page`.
        start: Start date for the date-range filter.
        end: End date for the date-range filter.
        back_url: URL for the back link.
        extra_params: Hidden form fields forwarded to :func:`render_date_filter`.
        extra_css: Additional CSS rules.

    Returns:
        Complete HTML page string.
    """
    filter_html = render_date_filter(start, end, extra_params=extra_params)

    if df.empty:
        return render_page(
            title,
            filter_html + "<h1>No data found</h1>",
            show_back_link=True,
            back_url=back_url,
        )

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    stats_html = f"<small>{len(df):,} data points</small>"

    return render_page(
        title,
        filter_html + stats_html + chart_html,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
        back_url=back_url,
        extra_css=extra_css,
    )


def render_comparison_result(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    left_device: str,
    left_measurement: str,
    right_device: str,
    right_measurement: str,
    start: date,
    end: date,
    title: str,
    *,
    back_url: str = "/compare",
) -> str:
    """Render a comparison chart page for one or two device/measurement pairs.

    Handles label creation, :func:`prepare_comparison`, chart type selection
    (dual-axis vs single line), and delegates to :func:`render_chart_page`.

    Args:
        left_df: DataFrame for the left axis (device, sensor, time, value).
        right_df: DataFrame for the right axis (may be empty).
        left_device: Device identifier for the left series.
        left_measurement: Measurement name for the left series.
        right_device: Device identifier for the right series (empty string if none).
        right_measurement: Measurement name for the right series (empty string if none).
        start: Start date for the date-range filter.
        end: End date for the date-range filter.
        title: Page ``<title>``.
        back_url: URL for the back link.

    Returns:
        Complete HTML page string.
    """
    from wp6_data.shared.charts import make_dual_axis_chart, make_line_chart, prepare_comparison

    has_right = bool(right_device and right_measurement)

    left_label = f"{left_device} | {left_measurement}"
    right_label = f"{right_device} | {right_measurement}" if has_right else ""
    df, left_label, right_label = prepare_comparison(
        left_df, right_df, left_label, right_label,
    )

    extra_params: dict[str, str] = {
        "left_device": left_device,
        "left_measurement": left_measurement,
    }
    if has_right:
        extra_params["right_device"] = right_device
        extra_params["right_measurement"] = right_measurement

    if has_right:
        fig = make_dual_axis_chart(df, left_label, right_label)
    else:
        fig = make_line_chart(df, title=left_label)

    return render_chart_page(
        df,
        fig,
        title,
        start,
        end,
        back_url=back_url,
        extra_params=extra_params,
    )
