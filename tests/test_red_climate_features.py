"""Tests for red's climate-model feature construction.

These pin the two rules the module exists to enforce: a lag is a duration, and
no row may know its own future.
"""

import numpy as np
import pandas as pd
import pytest

from wp6_data.red.climate.features import (
    build_supervised,
    hourly_frame,
    lag_columns,
    resample_hourly,
    seasonal_columns,
)


def _hours(n, start="2026-07-13", freq="h"):
    return pd.date_range(start, periods=n, freq=freq, tz="UTC")


class TestResampleHourly:
    def test_burst_writes_in_one_hour_collapse_to_one_row(self):
        """received_at is relay insert time, so it is not unique per device."""
        burst = pd.to_datetime(
            ["2026-07-13T05:00:01Z"] * 3 + ["2026-07-13T05:59:00Z"], utc=True
        )
        df = pd.DataFrame({"time": burst, "value": [10.0, 20.0, 30.0, 40.0]})

        out = resample_hourly(df)

        assert len(out) == 1
        assert out["value"].iloc[0] == pytest.approx(25.0)

    def test_null_values_are_dropped(self):
        df = pd.DataFrame(
            {"time": _hours(3), "value": [1.0, np.nan, 3.0]}
        )

        out = resample_hourly(df)

        assert out["value"].tolist() == [1.0, 3.0]

    def test_hours_with_no_readings_are_absent_not_zero_filled(self):
        times = pd.to_datetime(["2026-07-13T00:00Z", "2026-07-13T05:00Z"], utc=True)
        df = pd.DataFrame({"time": times, "value": [1.0, 2.0]})

        out = resample_hourly(df)

        assert len(out) == 2
        assert 0.0 not in out["value"].tolist()

    def test_empty_input_yields_typed_empty_frame(self):
        out = resample_hourly(pd.DataFrame({"time": [], "value": []}))

        assert out.empty
        assert list(out.columns) == ["time", "value"]


class TestHourlyFrame:
    def test_index_has_no_missing_hour_even_when_a_series_gaps(self):
        present = pd.DataFrame(
            {"time": _hours(3), "value": [1.0, 2.0, 3.0]}
        )
        late = pd.DataFrame(
            {"time": _hours(2, start="2026-07-13 06:00"), "value": [9.0, 9.5]}
        )

        frame = hourly_frame({"a": present, "b": late})

        assert len(frame) == 8  # 00:00 .. 07:00 inclusive, nothing missing
        assert frame["a"].isna().sum() == 5
        assert frame["b"].isna().sum() == 6


class TestLagColumns:
    def test_a_lag_is_a_duration_not_a_row_offset(self):
        """The whole reason the frame is reindexed before shifting."""
        frame = pd.DataFrame({"t": [0.0, 1.0, np.nan, np.nan, 4.0]}, index=_hours(5))

        lagged, names = lag_columns(frame, ["t"], [2])

        assert names == ["t", "t_lag2h"]
        # The row at 04:00 must look back to 02:00 — which is missing — not to
        # the previous *populated* row at 01:00.
        assert np.isnan(lagged["t_lag2h"].iloc[4])

    def test_lag_zero_is_included_as_the_bare_column(self):
        frame = pd.DataFrame({"t": [1.0, 2.0]}, index=_hours(2))

        lagged, names = lag_columns(frame, ["t"], [1])

        assert names[0] == "t"
        assert lagged["t"].tolist() == [1.0, 2.0]

    def test_unknown_column_is_skipped_not_invented(self):
        frame = pd.DataFrame({"t": [1.0]}, index=_hours(1))

        _, names = lag_columns(frame, ["t", "absent"], [1])

        assert names == ["t", "t_lag1h"]


class TestSeasonalColumns:
    def test_day_of_year_is_omitted_when_not_asked_for(self):
        """Link 3 has one season of data and must not fit a seasonal trend."""
        out = seasonal_columns(_hours(3), with_day_of_year=False)

        assert list(out.columns) == ["hour_of_day_sin", "hour_of_day_cos"]

    def test_hour_encoding_wraps_around_midnight(self):
        out = seasonal_columns(_hours(24), with_day_of_year=False)

        assert out["hour_of_day_sin"].iloc[0] == pytest.approx(0.0, abs=1e-9)
        assert out["hour_of_day_cos"].iloc[0] == pytest.approx(1.0)


class TestBuildSupervised:
    def _frame(self, n=48):
        index = _hours(n)
        return pd.DataFrame(
            {"temp": np.arange(n, dtype=float),
             "out_temp": np.arange(n, dtype=float) * 0.5},
            index=index,
        )

    def test_target_is_the_value_one_horizon_ahead(self):
        s = build_supervised(
            self._frame(), "temp", horizon_hours=3, lag_hours=[1],
            autoregressive=["temp"], exogenous=["out_temp"],
        )

        assert s.y[0] == s.y_now[0] + 3
        assert s.time_target.iloc[0] - s.time_at.iloc[0] == pd.Timedelta(hours=3)

    def test_no_row_uses_an_indoor_value_from_its_own_future(self):
        """The only thing at t+h is the target. An indoor feature there is a
        leak no held-out split can detect, because it lives inside the row."""
        s = build_supervised(
            self._frame(), "temp", horizon_hours=6, lag_hours=[1, 2],
            autoregressive=["temp"], exogenous=["out_temp"],
        )
        temp_at_t = s.X[:, s.feature_names.index("temp")]

        assert np.all(temp_at_t == s.y_now)
        assert np.all(s.y > temp_at_t)  # strictly increasing series, so no peeking

    def test_exogenous_features_are_read_at_the_target_time(self):
        """Weather at t+h is legitimate — a forecast supplies it."""
        s = build_supervised(
            self._frame(), "temp", horizon_hours=4, lag_hours=[],
            autoregressive=["temp"], exogenous=["out_temp"],
        )
        out_at = s.X[:, s.feature_names.index("out_temp")]

        assert out_at[0] == pytest.approx((s.y_now[0] + 4) * 0.5)

    def test_a_gap_removes_every_window_that_reaches_into_it(self):
        frame = self._frame()
        frame.loc[frame.index[10], "temp"] = np.nan

        s = build_supervised(
            frame, "temp", horizon_hours=2, lag_hours=[1],
            autoregressive=["temp"], exogenous=["out_temp"],
        )
        touched = {pd.Timestamp(t) for t in s.time_at}
        intact = build_supervised(
            self._frame(), "temp", horizon_hours=2, lag_hours=[1],
            autoregressive=["temp"], exogenous=["out_temp"],
        )

        dropped = {pd.Timestamp(t) for t in intact.time_at} - touched
        # A single missing hour invalidates three windows: the one whose lag0 it
        # is, the one whose lag1 it is, and the one whose target it is.
        assert dropped == {
            frame.index[10],      # lag 0
            frame.index[11],      # lag 1
            frame.index[8],       # target, two hours ahead
        }

    def test_days_are_carried_for_blocked_cross_validation(self):
        s = build_supervised(
            self._frame(), "temp", horizon_hours=1, lag_hours=[1],
            autoregressive=["temp"], exogenous=["out_temp"],
        )

        assert len(s.days) == len(s)
        assert len(set(s.days)) == 2  # 48 hours spans two calendar days

    def test_missing_target_column_yields_an_empty_set_not_a_crash(self):
        s = build_supervised(
            self._frame(), "absent", horizon_hours=1, lag_hours=[1],
        )

        assert len(s) == 0
        assert s.feature_names == []
