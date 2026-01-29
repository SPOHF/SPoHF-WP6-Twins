"""Shared HTML templates for WP6 dashboards."""

from datetime import date, timedelta


def default_date_range() -> tuple[date, date]:
    """Return default date range: last 7 days."""
    end = date.today()
    start = end - timedelta(days=7)
    return start, end


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

    btn_style = (
        "padding: 4px 12px; cursor: pointer; border: 1px solid #ccc;"
        " border-radius: 4px; background: #f5f5f5;"
    )
    active_style = (
        "padding: 4px 12px; cursor: pointer; border: 1px solid #0066cc;"
        " border-radius: 4px; background: #0066cc; color: white;"
    )

    buttons = []
    for label, days in presets:
        style = active_style if label == active else btn_style
        js_days = "null" if days is None else str(days)
        buttons.append(
            f'<button type="button" style="{style}" onclick="setRange({js_days})">'
            f"{label}</button>"
        )

    hidden_fields = ""
    if extra_params:
        hidden_fields = "".join(
            f'<input type="hidden" name="{k}" value="{v}">' for k, v in extra_params.items()
        )

    return f"""
    <form id="dateFilter" method="get" style="margin-bottom: 16px;">
        {hidden_fields}
        <div style="display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap;">
            {''.join(buttons)}
        </div>
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
            <label>From <input type="date" id="df-start" name="start"
                   value="{start.isoformat()}"></label>
            <label>To <input type="date" id="df-end" name="end"
                   value="{end.isoformat()}"></label>
            <button type="submit" style="{btn_style}">Apply</button>
        </div>
    </form>
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


BASE_CSS = """
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; }
    h1 { color: #333; }
    ul { line-height: 1.8; }
    a { color: #0066cc; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .logo { margin-bottom: 20px; }
    .logo img { max-height: 80px; }
    .back { margin-bottom: 20px; }
    footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
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
        '<footer><img src="/static/interreg.png" alt="Interreg" style="max-height: 60px;"></footer>'
        if show_footer
        else ""
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <style>
            {BASE_CSS}
            {extra_css}
        </style>
    </head>
    <body>
        {logo_html}
        {back_html}
        {content}
        {footer_html}
    </body>
    </html>
    """
