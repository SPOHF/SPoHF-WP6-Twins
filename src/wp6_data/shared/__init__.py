"""Shared components for WP6 dashboards."""

from wp6_data.shared.charts import make_dual_axis_chart, make_line_chart
from wp6_data.shared.templates import render_page

__all__ = ["make_line_chart", "make_dual_axis_chart", "render_page"]
