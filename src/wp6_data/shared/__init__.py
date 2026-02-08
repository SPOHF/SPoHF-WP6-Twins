"""Shared components for WP6 dashboards."""

from wp6_data.shared.charts import (
    make_bar_chart,
    make_dual_axis_chart,
    make_line_chart,
    make_schedule_chart,
    make_stacked_area_chart,
    prepare_comparison,
)
from wp6_data.shared.templates import (
    default_date_range,
    render_chart_page,
    render_compare_form,
    render_comparison_result,
    render_date_filter,
    render_page,
    resolve_date_range,
)

__all__ = [
    "default_date_range",
    "make_bar_chart",
    "make_dual_axis_chart",
    "make_line_chart",
    "make_schedule_chart",
    "make_stacked_area_chart",
    "prepare_comparison",
    "render_chart_page",
    "render_compare_form",
    "render_comparison_result",
    "render_date_filter",
    "render_page",
    "resolve_date_range",
]
