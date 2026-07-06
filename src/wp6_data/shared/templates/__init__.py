"""Shared HTML templates for WP6 dashboards.

Split into: :mod:`.config` (per-process dashboard identity),
:mod:`.assets` (CSS/JS loaded from ``static/shared/``),
:mod:`.components` (cards, tables, tabs, filters) and
:mod:`.pages` (full-page renderers). This package re-exports the public
surface so ``from wp6_data.shared.templates import render_page`` keeps
working.
"""

from wp6_data.shared.templates.assets import (
    BASE_CSS,
    DASHBOARD_CSS,
    DASHBOARD_JS,
    EXPLORE_TABS_JS,
    SAVE_TO_DASHBOARD_JS,
    TABLE_SORT_JS,
    THEME_JS,
    TOGGLE_JS,
    UNIFIED_CHART_JS,
)
from wp6_data.shared.templates.components import (
    EXPLORE_TAB_IDS,
    EXPLORE_TAB_LABELS,
    build_explore_tabs,
    chart_url,
    default_date_range,
    render_card,
    render_date_filter,
    render_device_table,
    render_explore_tabs,
    render_hub_card,
    render_hub_grid,
    render_manual_measurement_table,
    render_sensor_type_table,
    render_stat_grid,
    render_stat_tile,
    render_table,
    resolve_date_range,
    utc_day_bounds,
)
from wp6_data.shared.templates.config import (
    _current_user,
    configure_dashboard,
    require_dashboard_id,
)
from wp6_data.shared.templates.pages import (
    render_dashboard_page,
    render_nav_bar,
    render_page,
    render_unified_chart_page,
)

__all__ = [
    "BASE_CSS",
    "DASHBOARD_CSS",
    "DASHBOARD_JS",
    "EXPLORE_TABS_JS",
    "EXPLORE_TAB_IDS",
    "EXPLORE_TAB_LABELS",
    "SAVE_TO_DASHBOARD_JS",
    "TABLE_SORT_JS",
    "THEME_JS",
    "TOGGLE_JS",
    "UNIFIED_CHART_JS",
    "_current_user",
    "build_explore_tabs",
    "chart_url",
    "configure_dashboard",
    "default_date_range",
    "render_card",
    "render_dashboard_page",
    "render_date_filter",
    "render_device_table",
    "render_explore_tabs",
    "render_hub_card",
    "render_hub_grid",
    "render_manual_measurement_table",
    "render_nav_bar",
    "render_page",
    "render_sensor_type_table",
    "render_stat_grid",
    "render_stat_tile",
    "render_table",
    "render_unified_chart_page",
    "require_dashboard_id",
    "resolve_date_range",
    "utc_day_bounds",
]
