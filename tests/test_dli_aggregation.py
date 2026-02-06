"""Tests for wp6_data.red.dli.aggregation functions."""

import pandas as pd
import pytest

from wp6_data.red.dli.aggregation import (
    add_day_of_year_features,
    aggregate_to_daily,
    align_daily_dataframes,
    align_outdoor_to_indoor_daily,
    align_weather_to_outdoor_daily,
    encode_day_of_year,
)


class TestEncodeDayOfYear:
    def test_january_first(self):
        sin_val, cos_val = encode_day_of_year(1)
        assert sin_val == pytest.approx(0.0172, rel=0.01)
        assert cos_val == pytest.approx(1.0, rel=0.01)

    def test_april_first(self):
        # Day 91, roughly 1/4 through year
        sin_val, cos_val = encode_day_of_year(91)
        assert sin_val == pytest.approx(1.0, rel=0.05)
        assert cos_val == pytest.approx(0.0, abs=0.1)

    def test_july_first(self):
        # Day 182, roughly halfway through year
        sin_val, cos_val = encode_day_of_year(182)
        assert sin_val == pytest.approx(0.0, abs=0.1)
        assert cos_val == pytest.approx(-1.0, rel=0.05)

    def test_december_31(self):
        sin_val, cos_val = encode_day_of_year(365)
        # Should be close to January 1
        assert sin_val == pytest.approx(0.0, abs=0.1)
        assert cos_val == pytest.approx(1.0, rel=0.05)

    def test_returns_floats(self):
        sin_val, cos_val = encode_day_of_year(100)
        assert isinstance(sin_val, float)
        assert isinstance(cos_val, float)


class TestAddDayOfYearFeatures:
    def test_adds_sin_cos_columns(self):
        df = pd.DataFrame({"date": ["2026-01-01", "2026-07-01"]})
        result = add_day_of_year_features(df, date_col="date")
        assert "day_of_year_sin" in result.columns
        assert "day_of_year_cos" in result.columns

    def test_does_not_mutate_input(self):
        df = pd.DataFrame({"date": ["2026-01-01"]})
        cols_before = list(df.columns)
        add_day_of_year_features(df, date_col="date")
        assert list(df.columns) == cols_before

    def test_correct_values_for_january(self):
        df = pd.DataFrame({"date": ["2026-01-01"]})
        result = add_day_of_year_features(df, date_col="date")
        assert result["day_of_year_cos"].iloc[0] == pytest.approx(1.0, rel=0.01)

    def test_custom_date_column(self):
        df = pd.DataFrame({"my_date": ["2026-01-01"]})
        result = add_day_of_year_features(df, date_col="my_date")
        assert "day_of_year_sin" in result.columns


class TestAggregateToDaily:
    def _sample_hourly_df(self):
        times = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
        return pd.DataFrame({
            "time": times,
            "value": list(range(48)),
            "count": [1] * 48,
        })

    def test_aggregates_to_daily(self):
        df = self._sample_hourly_df()
        result = aggregate_to_daily(df, "time", {"value": "sum", "count": "sum"})
        assert len(result) == 2  # 2 days

    def test_applies_aggregation_functions(self):
        df = self._sample_hourly_df()
        result = aggregate_to_daily(df, "time", {"value": "sum"})
        # First day: 0+1+2+...+23 = 276
        assert result[result["date"] == pd.Timestamp("2026-01-01").date()]["value"].iloc[0] == 276

    def test_rename_columns(self):
        df = self._sample_hourly_df()
        result = aggregate_to_daily(
            df, "time", {"value": "sum"}, rename_map={"value": "value_sum"}
        )
        assert "value_sum" in result.columns


class TestAlignDailyDataframes:
    def _left_df(self):
        return pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "lux": list(range(48)),
        })

    def _right_df(self):
        return pd.DataFrame({
            "time": pd.date_range("2026-01-02", periods=24, freq="h", tz="UTC"),
            "par": list(range(24)),
        })

    def test_merges_on_date(self):
        left = self._left_df()
        right = self._right_df()
        result = align_daily_dataframes(
            left, right,
            left_time_col="time",
            right_time_col="time",
            left_agg={"lux": "sum"},
            right_agg={"par": "sum"},
        )
        # Only 2026-01-02 overlaps
        assert len(result) == 1

    def test_applies_minimum_filter(self):
        left = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "lux": [10] * 48,  # Sum = 240 per day
        })
        right = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "par": list(range(48)),
        })
        result = align_daily_dataframes(
            left, right,
            left_time_col="time",
            right_time_col="time",
            left_agg={"lux": "sum"},
            right_agg={"par": "sum"},
            min_left_value=250,
            min_left_col="lux",
        )
        # lux sum = 240 per day, filter is 250, so no rows pass
        assert len(result) == 0


class TestAlignWeatherToOutdoorDaily:
    def _weather_df(self):
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "solar_radiation": [100] * 48,
            "cloud_cover": [50] * 48,
        })

    def _outdoor_df(self):
        return pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "lux": [1000] * 48,
        })

    def test_returns_merged_data(self):
        weather = self._weather_df()
        outdoor = self._outdoor_df()
        result = align_weather_to_outdoor_daily(weather, outdoor)
        assert "lux_sum" in result.columns
        assert "direct_radiation_sum" in result.columns

    def test_renames_solar_to_direct(self):
        weather = self._weather_df()
        outdoor = self._outdoor_df()
        result = align_weather_to_outdoor_daily(weather, outdoor)
        assert "direct_radiation_sum" in result.columns
        assert "solar_radiation" not in result.columns

    def test_handles_direct_radiation(self):
        weather = pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "direct_radiation": [100] * 48,
        })
        outdoor = self._outdoor_df()
        result = align_weather_to_outdoor_daily(weather, outdoor)
        assert "direct_radiation_sum" in result.columns

    def test_filters_low_lux(self):
        weather = self._weather_df()
        outdoor = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "lux": [10] * 48,  # Sum = 240, below default threshold of 1000
        })
        result = align_weather_to_outdoor_daily(weather, outdoor)
        assert len(result) == 0


class TestAlignOutdoorToIndoorDaily:
    def _outdoor_df(self):
        return pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "lux": [1000] * 48,  # Sum = 24000 per day
        })

    def _indoor_df(self):
        return pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "value": [100] * 48,  # Sum = 2400 per day
        })

    def test_returns_merged_data(self):
        result = align_outdoor_to_indoor_daily(self._outdoor_df(), self._indoor_df())
        assert "lux_sum" in result.columns
        assert "par_sum" in result.columns

    def test_handles_value_column(self):
        # Indoor df uses 'value' column
        result = align_outdoor_to_indoor_daily(self._outdoor_df(), self._indoor_df())
        assert "par_sum" in result.columns

    def test_filters_low_lux(self):
        outdoor = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "lux": [10] * 24,  # Sum = 240, below threshold
        })
        result = align_outdoor_to_indoor_daily(outdoor, self._indoor_df())
        assert len(result) == 0

    def test_filters_low_par(self):
        indoor = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "value": [1] * 24,  # Sum = 24, below threshold of 100
        })
        result = align_outdoor_to_indoor_daily(self._outdoor_df(), indoor)
        assert len(result) == 0
