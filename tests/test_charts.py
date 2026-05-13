"""Tests for wp6_data.shared.charts."""

import pandas as pd

from wp6_data.shared.charts import (
    add_ideal_range,
    make_bar_chart,
    make_correlation_matrix,
    make_dual_axis_chart,
    make_line_chart,
    prepare_comparison,
)


def _sample_df():
    """Create a minimal sensor DataFrame for testing."""
    return pd.DataFrame(
        {
            "device": ["d1", "d1", "d2", "d2"],
            "sensor": ["temp", "temp", "temp", "temp"],
            "time": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"]),
            "value": [20.0, 21.0, 19.0, 20.5],
        }
    )


def _dual_axis_df():
    """Create a DataFrame with two sensor types."""
    return pd.DataFrame(
        {
            "device": ["d1", "d1", "d1", "d1"],
            "sensor": ["temp", "temp", "humidity", "humidity"],
            "time": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"]),
            "value": [20.0, 21.0, 55.0, 60.0],
        }
    )


class TestMakeLineChart:
    def test_returns_figure(self):
        fig = make_line_chart(_sample_df())
        assert fig is not None
        assert hasattr(fig, "data")

    def test_default_title(self):
        fig = make_line_chart(_sample_df())
        assert fig.layout.title.text == "Sensor Readings Over Time"

    def test_custom_title(self):
        fig = make_line_chart(_sample_df(), title="My Chart")
        assert fig.layout.title.text == "My Chart"

    def test_series_per_device(self):
        fig = make_line_chart(_sample_df())
        # Two devices → two traces
        assert len(fig.data) == 2

    def test_series_names_contain_device_and_sensor(self):
        fig = make_line_chart(_sample_df())
        names = {t.name for t in fig.data}
        assert "d1 | temp" in names
        assert "d2 | temp" in names

    def test_height_is_600(self):
        fig = make_line_chart(_sample_df())
        assert fig.layout.height == 600

    def test_hovermode_unified(self):
        fig = make_line_chart(_sample_df())
        assert fig.layout.hovermode == "x unified"

    def test_does_not_mutate_input(self):
        df = _sample_df()
        cols_before = list(df.columns)
        make_line_chart(df)
        assert list(df.columns) == cols_before
        assert "series" not in df.columns


class TestMakeDualAxisChart:
    def test_returns_figure(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        assert fig is not None

    def test_has_traces_for_both_axes(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        assert len(fig.data) == 2

    def test_trace_names(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        names = {t.name for t in fig.data}
        assert "d1 | temp" in names
        assert "d1 | humidity" in names

    def test_default_title(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        assert fig.layout.title.text == "temp vs humidity"

    def test_custom_title(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity", title="Compare")
        assert fig.layout.title.text == "Compare"

    def test_right_axis_uses_dashed_lines(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        # The humidity trace (right axis) should be dashed
        right_trace = [t for t in fig.data if "humidity" in t.name][0]
        assert right_trace.line.dash == "dash"

    def test_yaxis_labels(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        assert fig.layout.yaxis.title.text == "temp"
        assert fig.layout.yaxis2.title.text == "humidity"

    def test_height_is_600(self):
        fig = make_dual_axis_chart(_dual_axis_df(), "temp", "humidity")
        assert fig.layout.height == 600

    def test_empty_side(self):
        """Chart with no data for one axis should still render."""
        df = _dual_axis_df()
        fig = make_dual_axis_chart(df, "temp", "nonexistent")
        # Only temp traces
        assert len(fig.data) == 1

    def test_multiple_devices(self):
        df = pd.DataFrame(
            {
                "device": ["d1", "d1", "d2", "d2", "d1", "d1", "d2", "d2"],
                "sensor": ["temp"] * 4 + ["hum"] * 4,
                "time": pd.to_datetime(["2026-01-01", "2026-01-02"] * 4),
                "value": [20, 21, 19, 20, 55, 60, 50, 52],
            }
        )
        fig = make_dual_axis_chart(df, "temp", "hum")
        # 2 devices × 2 sensors = 4 traces
        assert len(fig.data) == 4


def _left_df():
    return pd.DataFrame({
        "device": ["d1", "d1"],
        "sensor": ["temp", "temp"],
        "time": pd.to_datetime(["2026-01-02", "2026-01-01"]),
        "value": [21.0, 20.0],
    })


def _right_df():
    return pd.DataFrame({
        "device": ["d2", "d2"],
        "sensor": ["humidity", "humidity"],
        "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "value": [55.0, 60.0],
    })


class TestPrepareComparison:
    def test_relabels_sensor_column(self):
        df, ll, rl = prepare_comparison(_left_df(), _right_df(), "Temp", "Humidity")
        assert set(df["sensor"].unique()) == {"Temp", "Humidity"}
        assert ll == "Temp"
        assert rl == "Humidity"

    def test_disambiguates_same_labels(self):
        df, ll, rl = prepare_comparison(_left_df(), _right_df(), "X", "X")
        assert ll == "X (left)"
        assert rl == "X (right)"
        assert set(df["sensor"].unique()) == {"X (left)", "X (right)"}

    def test_sorted_by_time(self):
        df, _, _ = prepare_comparison(_left_df(), _right_df(), "A", "B")
        times = df["time"].tolist()
        assert times == sorted(times)

    def test_does_not_mutate_inputs(self):
        left, right = _left_df(), _right_df()
        left_sensors = left["sensor"].tolist()
        right_sensors = right["sensor"].tolist()
        prepare_comparison(left, right, "A", "B")
        assert left["sensor"].tolist() == left_sensors
        assert right["sensor"].tolist() == right_sensors

    def test_left_empty(self):
        empty = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        df, ll, rl = prepare_comparison(empty, _right_df(), "A", "B")
        assert len(df) == 2
        assert set(df["sensor"].unique()) == {"B"}

    def test_right_empty(self):
        empty = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        df, ll, rl = prepare_comparison(_left_df(), empty, "A", "B")
        assert len(df) == 2
        assert set(df["sensor"].unique()) == {"A"}

    def test_both_empty(self):
        empty = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        df, _, _ = prepare_comparison(empty, empty, "A", "B")
        assert df.empty

    def test_combined_row_count(self):
        df, _, _ = prepare_comparison(_left_df(), _right_df(), "A", "B")
        assert len(df) == 4


# ---------------------------------------------------------------------------
# add_ideal_range
# ---------------------------------------------------------------------------

class TestAddIdealRange:
    def _base_fig(self):
        import plotly.graph_objects as go
        return go.Figure(go.Scatter(x=[1, 2], y=[10, 20]))

    def test_band_adds_one_shape(self):
        fig = add_ideal_range(self._base_fig(), lo=5.0, hi=15.0)
        assert len(fig.layout.shapes) == 1
        assert fig.layout.shapes[0].type == "rect"

    def test_mid_only_adds_line_shape(self):
        fig = add_ideal_range(self._base_fig(), mid=10.0)
        assert len(fig.layout.shapes) == 1
        assert fig.layout.shapes[0].type == "line"

    def test_band_and_mid_adds_two_shapes(self):
        fig = add_ideal_range(self._base_fig(), lo=5.0, hi=15.0, mid=10.0)
        assert len(fig.layout.shapes) == 2
        types = {s.type for s in fig.layout.shapes}
        assert "rect" in types
        assert "line" in types

    def test_no_params_adds_no_shapes(self):
        fig = add_ideal_range(self._base_fig())
        assert len(fig.layout.shapes) == 0

    def test_band_y_bounds(self):
        fig = add_ideal_range(self._base_fig(), lo=3.0, hi=7.0)
        shape = fig.layout.shapes[0]
        assert shape.y0 == 3.0
        assert shape.y1 == 7.0

    def test_mid_line_y_value(self):
        fig = add_ideal_range(self._base_fig(), mid=12.5)
        shape = fig.layout.shapes[0]
        assert shape.y0 == 12.5
        assert shape.y1 == 12.5

    def test_y_ref_right_axis(self):
        fig = add_ideal_range(self._base_fig(), lo=1.0, hi=2.0, y_ref="y2")
        assert fig.layout.shapes[0].yref == "y2"

    def test_horizontal_band_uses_paper_xref(self):
        fig = add_ideal_range(self._base_fig(), lo=1.0, hi=2.0)
        shape = fig.layout.shapes[0]
        assert shape.xref == "paper"
        assert shape.yref == "y"

    def test_returns_same_figure(self):
        fig = self._base_fig()
        result = add_ideal_range(fig, lo=1.0, hi=2.0)
        assert result is fig

    def test_appends_to_existing_shapes(self):
        import plotly.graph_objects as go
        fig = self._base_fig()
        fig.update_layout(shapes=[
            {"type": "line", "x0": 0, "x1": 1, "y0": 5, "y1": 5,
             "xref": "paper", "yref": "y"}
        ])
        add_ideal_range(fig, lo=1.0, hi=2.0)
        assert len(fig.layout.shapes) == 2


# ---------------------------------------------------------------------------
# make_bar_chart enhancements
# ---------------------------------------------------------------------------

def _bar_df():
    return pd.DataFrame({
        "treatment": ["A", "B", "C"],
        "value": [10.0, 15.0, 8.0],
    })


class TestMakeBarChartEnhancements:
    def test_vertical_default(self):
        fig = make_bar_chart(_bar_df(), x="treatment", y="value")
        assert fig is not None
        assert len(fig.data) == 1

    def test_horizontal_orientation(self):
        fig = make_bar_chart(_bar_df(), x="treatment", y="value", orientation="h")
        # px.bar with orientation='h' swaps x/y internally
        assert fig is not None

    def test_horizontal_hovermode_is_y_unified(self):
        fig = make_bar_chart(_bar_df(), x="treatment", y="value", orientation="h")
        assert fig.layout.hovermode == "y unified"

    def test_vertical_hovermode_is_x_unified(self):
        fig = make_bar_chart(_bar_df(), x="treatment", y="value", orientation="v")
        assert fig.layout.hovermode == "x unified"

    def test_ideal_range_adds_shape_vertical(self):
        fig = make_bar_chart(
            _bar_df(), x="treatment", y="value",
            ideal_lo=9.0, ideal_hi=14.0,
        )
        assert len(fig.layout.shapes) >= 1

    def test_ideal_range_adds_shape_horizontal(self):
        fig = make_bar_chart(
            _bar_df(), x="treatment", y="value", orientation="h",
            ideal_lo=9.0, ideal_hi=14.0,
        )
        assert len(fig.layout.shapes) >= 1

    def test_no_ideal_range_no_shapes(self):
        fig = make_bar_chart(_bar_df(), x="treatment", y="value")
        assert len(fig.layout.shapes) == 0

    def test_ideal_mid_only_adds_line(self):
        fig = make_bar_chart(_bar_df(), x="treatment", y="value", ideal_mid=11.0)
        assert any(s.type == "line" for s in fig.layout.shapes)

    def test_backward_compatible_no_new_params(self):
        # Original 8-param signature must still work unchanged
        fig = make_bar_chart(
            _bar_df(), x="treatment", y="value",
            color=None, title="T", y_label="Val",
            barmode="group", text_auto=True,
        )
        assert fig.layout.title.text == "T"


# ---------------------------------------------------------------------------
# make_correlation_matrix
# ---------------------------------------------------------------------------

def _corr_df():
    """Two sensor series with a known positive correlation."""
    import numpy as np
    times = pd.date_range("2026-01-01", periods=48, freq="1h", tz="UTC")
    x = np.linspace(0, 4 * 3.14159, 48)
    return pd.DataFrame({
        "device": ["d1"] * 48 + ["d1"] * 48,
        "sensor": ["temp"] * 48 + ["hum"] * 48,
        "time": list(times) * 2,
        "value": list(np.sin(x) * 5 + 20) + list(np.sin(x) * 10 + 60),
    })


class TestMakeCorrelationMatrix:
    def test_returns_figure(self):
        fig = make_correlation_matrix(_corr_df())
        assert fig is not None

    def test_has_heatmap_trace(self):
        import plotly.graph_objects as go
        fig = make_correlation_matrix(_corr_df())
        assert any(isinstance(t, go.Heatmap) for t in fig.data)

    def test_matrix_values_in_range(self):
        import numpy as np
        fig = make_correlation_matrix(_corr_df())
        z = fig.data[0].z
        valid = [v for row in z for v in row if v is not None and not np.isnan(v)]
        assert all(-1.0 <= v <= 1.0 for v in valid)

    def test_diagonal_is_one(self):
        import numpy as np
        fig = make_correlation_matrix(_corr_df())
        z = fig.data[0].z
        for i in range(len(z)):
            assert abs(z[i][i] - 1.0) < 1e-6

    def test_sensor_filter(self):
        # With filter to one key → fewer than 2 sensors → fallback figure
        fig = make_correlation_matrix(_corr_df(), sensors=["d1:temp"])
        # Should return figure with annotation, no heatmap
        assert len(fig.data) == 0 or not any(
            hasattr(t, "zmin") for t in fig.data
        )

    def test_custom_title(self):
        fig = make_correlation_matrix(_corr_df(), title="My Matrix")
        assert fig.layout.title.text == "My Matrix"

    def test_empty_df_returns_figure(self):
        empty = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        fig = make_correlation_matrix(empty)
        assert fig is not None
        assert len(fig.data) == 0

    def test_upper_triangle_is_nan(self):
        import numpy as np
        fig = make_correlation_matrix(_corr_df())
        z = fig.data[0].z
        # z[0][1] is upper-triangle (row 0, col 1) → should be NaN
        assert np.isnan(z[0][1])
