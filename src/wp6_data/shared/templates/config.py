"""Per-process dashboard identity and theme, set once at startup.

The platform runs one twin per process; ``create_app`` calls
:func:`configure_dashboard` with the twin's identity before any page is
rendered. There is deliberately no default identity — shared code must not
assume a twin — so rendering before configuration fails loudly.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wp6_data.shared.twin import DataSource, ThemeColors

_dashboard_id: str | None = None
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


def require_dashboard_id() -> str:
    """The configured twin id; raises if configure_dashboard was never called."""
    if _dashboard_id is None:
        raise RuntimeError(
            "configure_dashboard() must be called before rendering pages",
        )
    return _dashboard_id
