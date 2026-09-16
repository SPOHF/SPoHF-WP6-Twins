"""Tests for the model page's performance matrices.

The concern is that a matrix cannot flatter the model: zero must land on the
neutral midpoint, a weak run must look weak, and a combination that was never
fitted must read as a gap rather than as a score of nothing.
"""

import pytest

from wp6_data.red.climate.charts import (
    MIN_SKILL_BOUND,
    diverging_bound,
    hour_error_chart,
    skill_matrix_chart,
)
from wp6_data.shared.charts import render_matrix_heatmap_html


class TestDivergingBound:
    def test_is_symmetric_so_grey_lands_on_zero(self):
        """An asymmetric range would put the neutral colour somewhere other
        than 'no better than the baseline'."""
        bound = diverging_bound([0.67, -0.12])

        assert bound == pytest.approx(0.7)

    def test_a_weak_run_is_not_painted_as_a_triumph(self):
        """Without a floor, everything scoring ±0.03 would fill the scale."""
        assert diverging_bound([0.03, -0.02]) == MIN_SKILL_BOUND

    def test_ignores_missing_cells(self):
        assert diverging_bound([None, 0.4, None]) == pytest.approx(0.4)

    def test_an_empty_matrix_still_yields_the_floor(self):
        assert diverging_bound([]) == MIN_SKILL_BOUND


class TestSkillMatrix:
    def test_nothing_to_draw_returns_none(self):
        assert skill_matrix_chart([], [], [], baseline="persistence") is None

    def test_renders_with_the_diverging_scale_and_a_symmetric_range(self):
        html = skill_matrix_chart(
            [[0.5, -0.2]], ["+1 h", "+6 h"], ["temp"], baseline="persistence",
        )

        assert html is not None
        assert '"zmin":-0.5' in html.replace(" ", "")
        assert '"zmax":0.5' in html.replace(" ", "")
        # grey midpoint, not a hue
        assert "#f0efec" in html


class TestHourErrorChart:
    def test_no_stored_residuals_returns_none(self):
        """An older model has none; the page says so rather than drawing an
        empty grid."""
        assert hour_error_chart([(1, []), (6, [])], "°C") is None

    def test_draws_one_row_per_horizon_that_has_residuals(self):
        html = hour_error_chart(
            [(1, [(0, 0.9), (12, 1.4)]), (6, []), (24, [(0, 2.0), (12, 4.5)])],
            "°C",
        )

        assert html is not None
        assert "+1 h" in html
        assert "+24 h" in html
        assert "+6 h" not in html


class TestMatrixGaps:
    def test_a_missing_cell_is_a_gap_not_a_zero(self):
        """A combination that was never fitted is not a score of nothing."""
        html = render_matrix_heatmap_html(
            [[1.0, None], [float("nan"), 2.0]], ["a", "b"], ["x", "y"],
        )

        assert "hoverongaps" in html
        assert html.count("null") >= 1

    def test_values_are_printed_as_well_as_coloured(self):
        html = render_matrix_heatmap_html([[0.42]], ["a"], ["x"])

        assert "0.42" in html
        assert "texttemplate" in html

    def test_correlation_heatmap_keeps_its_fixed_range(self):
        import pandas as pd

        from wp6_data.shared.charts import render_correlation_heatmap_html

        frame = pd.DataFrame([[1.0, 0.5], [0.5, 1.0]], columns=["a", "b"], index=["a", "b"])

        html = render_correlation_heatmap_html(frame, ["a", "b"])

        compact = html.replace(" ", "")
        assert '"zmin":-1' in compact
        assert '"zmax":1' in compact


class TestPeriodErrorCharts:
    def test_month_chart_labels_months_not_numbers(self):
        from wp6_data.red.climate.charts import month_error_chart

        html = month_error_chart([(1, [(1, 62.7), (7, 240.8)])], "µmol/m²/s")

        assert html is not None
        assert "Jan" in html
        assert "Jul" in html

    def test_hour_and_month_share_one_builder(self):
        """Two ways a single RMSE misleads — part of the day, part of the year
        — so they are the same chart with a different key."""
        from wp6_data.red.climate.charts import hour_error_chart, month_error_chart

        hour = hour_error_chart([(1, [(0, 1.0), (12, 2.0)])], "°C")
        month = month_error_chart([(1, [(1, 1.0), (7, 2.0)])], "°C")

        assert "hour of day" in hour
        assert "month" in month

    def test_unitless_target_still_labels_the_scale(self):
        from wp6_data.red.climate.charts import month_error_chart

        html = month_error_chart([(1, [(1, 0.5)])], "")

        assert "RMSE" in html

    def test_no_stored_residuals_returns_none(self):
        from wp6_data.red.climate.charts import month_error_chart

        assert month_error_chart([(1, []), (6, [])], "°C") is None
