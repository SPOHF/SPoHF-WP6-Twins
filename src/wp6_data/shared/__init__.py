"""Shared components for WP6 dashboards."""

from wp6_data.shared.charts import (
    build_weekly_coverage,
    make_bar_chart,
    make_dual_axis_chart,
    make_line_chart,
    make_schedule_chart,
    make_stacked_area_chart,
    prepare_comparison,
    render_coverage_grid,
)
from wp6_data.shared.templates import (
    default_date_range,
    render_card,
    render_date_filter,
    render_page,
    render_table,
    render_unified_chart_page,
    resolve_date_range,
    utc_day_bounds,
)

__all__ = [
    "build_weekly_coverage",
    "default_date_range",
    "make_bar_chart",
    "make_dual_axis_chart",
    "make_line_chart",
    "make_schedule_chart",
    "make_stacked_area_chart",
    "prepare_comparison",
    "render_card",
    "render_coverage_grid",
    "render_date_filter",
    "render_page",
    "render_table",
    "render_unified_chart_page",
    "resolve_date_range",
    "utc_day_bounds",
]
