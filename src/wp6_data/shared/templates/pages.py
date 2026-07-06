"""Full-page renderers: the page shell, unified chart page, and dashboard page."""

from __future__ import annotations

from datetime import date

from wp6_data.shared.templates import config
from wp6_data.shared.templates.assets import (
    DASHBOARD_CSS,
    EXPLORE_TABS_JS,
    THEME_JS,
    TOGGLE_JS,
    asset_url,
)
from wp6_data.shared.templates.components import render_date_filter


def _render_source_indicator(active_source: str | None) -> str:
    """Render a data-source indicator in the nav bar.

    Single source: static badge. Multiple sources: interactive dropdown.
    """
    if not config._data_sources:
        return ""
    icon = '<span style="font-size:0.9rem;opacity:0.6">\u26c1</span>'
    if len(config._data_sources) == 1:
        label = config._data_sources[0].label
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
        for ds in config._data_sources
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
    if len(config._data_sources) < 2:
        return ""
    cookie_name = f"wp6_{config.require_dashboard_id()}_source"
    return f"""
    function switchSource(value) {{
        document.cookie = '{cookie_name}=' + value + ';path=/;max-age=31536000';
        location.reload();
    }}
"""


def render_nav_bar(
    *, data_source: str | None = None, show_source_indicator: bool = True,
) -> str:
    """Render a sticky nav bar with dashboard name, home link, and dark mode toggle."""
    name = config._dashboard_title
    user = config._current_user.get()
    # Source-independent pages (e.g. GDD, now OpenMeteo-backed) opt out of the
    # data-source indicator so they don't imply the toggle affects their data.
    source_html = _render_source_indicator(data_source) if show_source_indicator else ""

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
    show_source_indicator: bool = True,
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
    <html data-dashboard="{config.require_dashboard_id()}">
    <head>
        <title>{title}</title>
        <link rel="icon" href="/static/favicon.ico" type="image/x-icon">
        <link rel="stylesheet"
              href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css">
        <script>{THEME_JS}</script>
        <link rel="stylesheet" href="{asset_url('base.css')}">
        <style>
            {config._twin_theme_css}
            {extra_css}
        </style>
    </head>
    <body>
        {render_nav_bar(data_source=data_source, show_source_indicator=show_source_indicator)}
        <main>
            {back_html}
            {content}
            {footer_html}
        </main>
        <script>{TOGGLE_JS}</script>
        <script>{_source_toggle_js()}</script>
        <script src="{asset_url('table_sort.js')}"></script>
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
                </div>
            </details>
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
    <script src="{asset_url('unified_chart.js')}"></script>
    <script src="{asset_url('save_to_dashboard.js')}"></script>
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
    <script src="{asset_url('dashboard.js')}"></script>
    """
    return render_page(
        f"{title_prefix} — Dashboard",
        content,
        show_logo=False,
        show_footer=True,
        extra_css=DASHBOARD_CSS,
        data_source=data_source,
    )
