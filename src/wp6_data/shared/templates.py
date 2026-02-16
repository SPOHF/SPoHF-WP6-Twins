"""Shared HTML templates for WP6 dashboards."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go


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
    }
    h1 { --pico-typography-spacing-vertical: 1rem; }
    article { padding: 1rem; }
    .date-filter { padding: 0.75rem 1rem; }
    .date-filter form { margin-bottom: 0; }
    .date-presets { display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
    .date-presets button { width: auto; padding: 0.25rem 0.75rem; margin-bottom: 0; }
    .date-inputs { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .date-inputs label { margin-bottom: 0; }
    .date-inputs button { width: auto; padding: 0.25rem 0.75rem; margin-bottom: 0; }
    .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
    .stats-grid.cols-4 { grid-template-columns: repeat(4, 1fr); }
    .stats-grid.cols-5 { grid-template-columns: repeat(5, 1fr); }
    .stats-grid.cols-auto { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
    .stats-grid article { text-align: center; margin-bottom: 0; }
    .stat-value { font-size: 1.5em; font-weight: bold; color: #0066cc; }
    .success { color: green !important; }
    .warning { color: #cc6600 !important; }
    .compare-axes { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
    .compare-selects { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .compare-selects label { margin-bottom: 0; }
    .back { margin-bottom: 20px; }
    .logo { margin-bottom: 20px; }
    .logo img { max-height: 80px; }
    footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
    .footer-logo { max-height: 60px; }
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
    logo_html = (
        '<div class="logo"><img src="/static/interreg.png" alt="Interreg Logo"></div>'
        if show_logo
        else ""
    )

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
    <html data-theme="light">
    <head>
        <title>{title}</title>
        <link rel="icon" href="/static/favicon.ico" type="image/x-icon">
        <link rel="stylesheet"
              href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css">
        <style>
            {BASE_CSS}
            {extra_css}
        </style>
    </head>
    <body>
        <main>
            {logo_html}
            {back_html}
            {content}
            {footer_html}
        </main>
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
