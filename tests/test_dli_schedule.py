"""Tests for wp6_data.red.dli.schedule functions."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from wp6_data.red.dli.schedule import (
    distribute_dli_across_hours,
    estimate_remaining_dli,
    infer_lamp_schedule_hourly,
    prepare_daily_dli_summary,
)


class MockHourlyForecast:
    """Mock hourly forecast object."""

    def __init__(self, hour: int, solar_radiation: float):
        self.datetime = datetime(2026, 1, 1, hour, tzinfo=UTC)
        self.solar_radiation = solar_radiation


class TestInferLampScheduleHourly:
    def _sample_hourly_df(self):
        """Create sample hourly PAR averages."""
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "par_avg": [0] * 6 + [100, 150, 200, 250, 300, 250, 200, 150, 100, 50] + [0] * 8,
        })

    def _sample_forecasts(self):
        """Create mock hourly forecasts."""
        return [MockHourlyForecast(h, 100.0 if 6 <= h <= 18 else 0.0) for h in range(24)]

    def test_returns_dict_with_24_hours(self):
        hourly_df = self._sample_hourly_df()
        forecasts = self._sample_forecasts()
        result = infer_lamp_schedule_hourly(hourly_df, 5.0, forecasts, 1300.0)
        assert len(result) == 24
        assert all(0 <= h <= 23 for h in result)

    def test_lamp_contribution_non_negative(self):
        hourly_df = self._sample_hourly_df()
        forecasts = self._sample_forecasts()
        result = infer_lamp_schedule_hourly(hourly_df, 5.0, forecasts, 1300.0)
        assert all(v >= 0 for v in result.values())

    def test_night_hours_have_zero_natural(self):
        hourly_df = pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "par_avg": [100] * 24,  # Constant PAR (from lamps)
        })
        forecasts = self._sample_forecasts()
        result = infer_lamp_schedule_hourly(hourly_df, 5.0, forecasts, 1300.0)
        # At night (hour 0-5, 19-23), all PAR should be attributed to lamps
        assert result[0] == pytest.approx(100.0, rel=0.01)


class TestDistributeDliAcrossHours:
    def _sample_forecasts(self):
        """Create mock hourly forecasts with varying radiation."""
        return [MockHourlyForecast(h, 100.0 if 6 <= h <= 18 else 0.0) for h in range(24)]

    def test_returns_dict_with_24_hours(self):
        forecasts = self._sample_forecasts()
        result = distribute_dli_across_hours(10.0, forecasts, 1300.0)
        assert len(result) == 24

    def test_total_matches_input_dli(self):
        forecasts = self._sample_forecasts()
        result = distribute_dli_across_hours(10.0, forecasts, 1300.0)
        # Sum of hourly PAR * 3600 / 1e6 should equal DLI
        total_dli = sum(result.values()) * 3600 / 1_000_000
        assert total_dli == pytest.approx(10.0, rel=0.01)

    def test_night_hours_are_zero(self):
        forecasts = self._sample_forecasts()
        result = distribute_dli_across_hours(10.0, forecasts, 1300.0)
        for h in range(6):
            assert result[h] == 0.0
        for h in range(19, 24):
            assert result[h] == 0.0


class TestPrepareDailyDliSummary:
    def _actual_df(self):
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01 06:00", periods=12, freq="h", tz="UTC"),
            "par": [100] * 12,
        })

    def _predicted_df(self):
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "par": [50] * 24,
        })

    def _natural_df(self):
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "par": [30] * 24,
        })

    def test_returns_dict_with_dates(self):
        result = prepare_daily_dli_summary(
            self._actual_df(), self._predicted_df(), self._natural_df()
        )
        assert isinstance(result, dict)
        assert date(2026, 1, 1) in result

    def test_includes_actual_predicted_natural(self):
        result = prepare_daily_dli_summary(
            self._actual_df(), self._predicted_df(), self._natural_df()
        )
        day = result[date(2026, 1, 1)]
        assert "actual" in day
        assert "predicted" in day
        assert "natural" in day

    def test_handles_none_inputs(self):
        result = prepare_daily_dli_summary(None, None, None)
        assert result == {}

    def test_handles_empty_dataframes(self):
        empty = pd.DataFrame(columns=["datetime", "par"])
        result = prepare_daily_dli_summary(empty, empty, empty)
        assert result == {}

    def test_handles_partial_inputs(self):
        result = prepare_daily_dli_summary(self._actual_df(), None, None)
        day = result[date(2026, 1, 1)]
        assert "actual" in day
        assert "predicted" not in day


class TestEstimateRemainingDli:
    def _predicted_df(self):
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC"),
            "par": [100] * 24,  # 100 PAR each hour
        })

    def test_returns_remaining_dli(self):
        result = estimate_remaining_dli(self._predicted_df(), date(2026, 1, 1), current_hour=12)
        # 11 hours remaining (13-23), 100 PAR each * 3600 / 1e6
        expected = 11 * 100 * 3600 / 1_000_000
        assert result == pytest.approx(expected, rel=0.01)

    def test_returns_zero_at_end_of_day(self):
        result = estimate_remaining_dli(self._predicted_df(), date(2026, 1, 1), current_hour=23)
        assert result == 0.0

    def test_returns_full_day_at_start(self):
        result = estimate_remaining_dli(self._predicted_df(), date(2026, 1, 1), current_hour=0)
        # 23 hours remaining (1-23)
        expected = 23 * 100 * 3600 / 1_000_000
        assert result == pytest.approx(expected, rel=0.01)

    def test_returns_zero_for_wrong_date(self):
        result = estimate_remaining_dli(self._predicted_df(), date(2026, 1, 2), current_hour=12)
        assert result == 0.0

    def test_handles_none_input(self):
        result = estimate_remaining_dli(None, date(2026, 1, 1), current_hour=12)
        assert result == 0.0

    def test_handles_empty_dataframe(self):
        empty = pd.DataFrame(columns=["datetime", "par"])
        result = estimate_remaining_dli(empty, date(2026, 1, 1), current_hour=12)
        assert result == 0.0
