"""Tests for wp6_data.red.dli.calculator functions."""

from datetime import date

import pandas as pd
import pytest

from wp6_data.red.dli.calculator import (
    calculate_daily_dli,
    calculate_dli_trendline,
    calculate_hourly_par,
    calculate_lamp_contribution,
    estimate_hourly_natural_par,
    par_sum_to_dli,
)


class TestCalculateDliTrendline:
    def test_returns_trendline_and_slope(self):
        dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
        values = [10.0, 12.0, 14.0]
        trendline_y, slope = calculate_dli_trendline(dates, values)
        assert len(trendline_y) == 3
        assert slope == pytest.approx(2.0, rel=0.01)

    def test_returns_empty_for_single_point(self):
        trendline_y, slope = calculate_dli_trendline([date(2026, 1, 1)], [10.0])
        assert len(trendline_y) == 0
        assert slope == 0.0

    def test_flat_trendline(self):
        dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
        values = [10.0, 10.0, 10.0]
        trendline_y, slope = calculate_dli_trendline(dates, values)
        assert slope == pytest.approx(0.0, abs=0.01)

    def test_negative_slope(self):
        dates = [date(2026, 1, 1), date(2026, 1, 2)]
        values = [20.0, 10.0]
        _, slope = calculate_dli_trendline(dates, values)
        assert slope == pytest.approx(-10.0, rel=0.01)


class TestCalculateLampContribution:
    def test_positive_contribution(self):
        result = calculate_lamp_contribution(15.0, 10.0)
        assert result == 5.0

    def test_zero_contribution(self):
        result = calculate_lamp_contribution(10.0, 10.0)
        assert result == 0.0

    def test_negative_contribution(self):
        # Total < natural (unusual but possible due to sensor differences)
        result = calculate_lamp_contribution(8.0, 10.0)
        assert result == -2.0

    def test_none_total(self):
        result = calculate_lamp_contribution(None, 10.0)
        assert result is None

    def test_none_natural(self):
        result = calculate_lamp_contribution(15.0, None)
        assert result is None

    def test_both_none(self):
        result = calculate_lamp_contribution(None, None)
        assert result is None


class TestEstimateHourlyNaturalPar:
    def test_proportional_distribution(self):
        # 10 mol DLI, hour has 20% of total radiation
        daily_dli = 10.0
        hour_radiation = 200.0
        total_radiation = 1000.0
        result = estimate_hourly_natural_par(daily_dli, hour_radiation, total_radiation)
        # Expected: 10 * 0.2 * 1_000_000 / 3600 = 555.56
        assert result == pytest.approx(555.56, rel=0.01)

    def test_zero_total_radiation(self):
        result = estimate_hourly_natural_par(10.0, 100.0, 0.0)
        assert result == 0.0

    def test_zero_hour_radiation(self):
        result = estimate_hourly_natural_par(10.0, 0.0, 1000.0)
        assert result == 0.0

    def test_full_day_radiation_in_one_hour(self):
        # All radiation in one hour
        daily_dli = 10.0
        result = estimate_hourly_natural_par(daily_dli, 1000.0, 1000.0)
        # Expected: 10 * 1_000_000 / 3600 = 2777.78
        assert result == pytest.approx(2777.78, rel=0.01)


class TestParSumToDli:
    def test_default_interval(self):
        # PAR sum of 1000, 600 seconds per reading
        result = par_sum_to_dli(1000.0)
        # Expected: 1000 * 600 / 1_000_000 = 0.6
        assert result == 0.6

    def test_custom_interval(self):
        # PAR sum of 1000, 1800 seconds per reading (30 min)
        result = par_sum_to_dli(1000.0, seconds_per_reading=1800.0)
        # Expected: 1000 * 1800 / 1_000_000 = 1.8
        assert result == 1.8

    def test_zero_sum(self):
        result = par_sum_to_dli(0.0)
        assert result == 0.0


class TestCalculateDailyDli:
    def _sample_par_df(self):
        """Create sample PAR readings for one day."""
        times = pd.date_range("2026-01-01 00:00", periods=18, freq="h", tz="UTC")
        # Simulate daylight: low at 6am, peak at noon, low at 6pm (18 hours, all in one day)
        par_values = [0] * 6 + [50, 150, 300, 500, 700, 800, 700, 500, 300, 150, 50, 0]
        return pd.DataFrame({
            "device": ["sensor1"] * 18,
            "sensor": ["par"] * 18,
            "time": times,
            "value": par_values,
        })

    def test_returns_expected_columns(self):
        df = self._sample_par_df()
        result = calculate_daily_dli(df)
        expected_cols = {"date", "device", "dli", "avg_par", "photoperiod_hours", "reading_count"}
        assert set(result.columns) == expected_cols

    def test_returns_one_row_per_device_per_day(self):
        df = self._sample_par_df()
        result = calculate_daily_dli(df)
        assert len(result) == 1

    def test_empty_input(self):
        df = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        result = calculate_daily_dli(df)
        assert result.empty

    def test_photoperiod_counts_daylight_hours(self):
        df = self._sample_par_df()
        result = calculate_daily_dli(df)
        # With threshold=10, hours 7:00 to 17:00 should count (11 hours of >10 PAR)
        assert result["photoperiod_hours"].iloc[0] > 0


class TestCalculateHourlyPar:
    def _sample_par_df(self):
        """Create sample PAR readings at 10-min intervals."""
        times = pd.date_range("2026-01-01 10:00", periods=12, freq="10min", tz="UTC")
        return pd.DataFrame({
            "device": ["sensor1"] * 12,
            "sensor": ["par"] * 12,
            "time": times,
            "value": [100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210],
        })

    def test_returns_expected_columns(self):
        df = self._sample_par_df()
        result = calculate_hourly_par(df)
        expected_cols = {"datetime", "device", "par_avg", "par_max", "reading_count"}
        assert set(result.columns) == expected_cols

    def test_aggregates_to_hourly(self):
        df = self._sample_par_df()
        result = calculate_hourly_par(df)
        # 2 hours: 10:00 and 11:00
        assert len(result) == 2

    def test_calculates_avg_and_max(self):
        df = self._sample_par_df()
        result = calculate_hourly_par(df)
        # First hour (10:00): values 100, 110, 120, 130, 140, 150
        first_hour = result[result["datetime"].dt.hour == 10].iloc[0]
        assert first_hour["par_avg"] == pytest.approx(125.0, rel=0.01)
        assert first_hour["par_max"] == 150.0

    def test_empty_input(self):
        df = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        result = calculate_hourly_par(df)
        assert result.empty
