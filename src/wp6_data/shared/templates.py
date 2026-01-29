"""Shared HTML templates for WP6 dashboards."""

from datetime import date, timedelta


def default_date_range() -> tuple[date, date]:
    """Return default date range: last 7 days."""
    end = date.today()
    start = end - timedelta(days=7)
    return start, end


def render_date_filter(start: date, end: date) -> str:
    """Render an HTML date-range filter form."""
    return f"""
    <form method="get" style="margin-bottom: 16px; display: flex;
          align-items: center; gap: 10px; flex-wrap: wrap;">
        <label>From <input type="date" name="start" value="{start.isoformat()}"></label>
        <label>To <input type="date" name="end" value="{end.isoformat()}"></label>
        <button type="submit" style="padding: 4px 16px; cursor: pointer;">Apply</button>
    </form>
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
