"""Tests for wp6_data.shared.charts."""

import pandas as pd

from wp6_data.shared.charts import make_dual_axis_chart, make_line_chart, prepare_comparison


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
