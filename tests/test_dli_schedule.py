"""Tests for wp6_data.red.dli.schedule functions."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from wp6_data.red.dli.constants import SECONDS_PER_HOUR, UMOL_TO_MOL
from wp6_data.red.dli.schedule import (
    compute_daily_predicted_dli,
    distribute_dli_across_hours,
    estimate_remaining_dli,
    lamp_hourly_par,
    prepare_daily_dli_summary,
)
from wp6_data.red.lamp import LAMP_THRESHOLD, LampModel, derive_lamp_model


class MockHourlyForecast:
    """Mock hourly forecast object."""

    def __init__(self, hour: int, solar_radiation: float):
        self.datetime = datetime(2026, 1, 1, hour, tzinfo=UTC)
        self.solar_radiation = solar_radiation


class MockDailyForecast:
    """Mock daily forecast: 24 hourly entries, sun up 06:00-18:00."""

    def __init__(self, day: date):
        self.date = day
        self.hourly = [
            MockHourlyForecast(h, 100.0 if 6 <= h <= 18 else 0.0) for h in range(24)
        ]
        for h in self.hourly:
            h.datetime = h.datetime.replace(year=day.year, month=day.month, day=day.day)

    @property
    def total_radiation(self) -> float:
        return sum(h.solar_radiation for h in self.hourly)


def _par_frame(day: date, values_by_hour: dict[int, float]) -> pd.DataFrame:
    """PAR readings frame in the shape derive_lamp_model expects."""
    rows = []
    for offset in range(14):  # a fortnight of identical days
        d = day - timedelta(days=offset)
        for hour, value in values_by_hour.items():
            rows.append({"time": datetime(d.year, d.month, d.day, hour, tzinfo=UTC),
                         "value": value})
    return pd.DataFrame(rows)


class TestLampHourlyPar:
    def test_none_model_is_a_day_of_zeros(self):
        schedule = lamp_hourly_par(None)
        assert len(schedule) == 24
        assert set(schedule.values()) == {0.0}

    def test_model_that_is_not_lighting_is_a_day_of_zeros(self):
        lamp = LampModel(0.8, 5, None, frozenset(), observed_days=14)
        assert set(lamp_hourly_par(lamp).values()) == {0.0}

    def test_lit_hours_carry_the_measured_power(self):
        lamp = LampModel(0.8, 5, 160.0, frozenset({4, 5}), observed_days=14)
        schedule = lamp_hourly_par(lamp)
        assert schedule[4] == 160.0
        assert schedule[5] == 160.0
        assert schedule[12] == 0.0


class TestComputeDailyPredictedDli:
    """The bug this guards: predicted DLI used to exceed natural on lamp-off days.

    Lamp light was derived as ``max(0, actual - natural)`` per hour, which keeps
    positive residuals and discards negative ones. Any disagreement between the
    greenhouse's intraday shape and the open-field radiation curve was therefore
    rectified into lamp light that could never be zero.
    """

    def test_lamps_off_means_predicted_equals_natural(self):
        day = date(2026, 6, 21)
        forecast = MockDailyForecast(day)
        natural = {day: 42.0}
        assert compute_daily_predicted_dli([forecast], natural, None)[day] == 42.0

    def test_long_day_read_from_sensors_adds_no_lamp(self):
        """End-to-end: a long summer day, lamps genuinely off, from raw PAR."""
        day = date(2026, 6, 21)
        # Sun up 04:00-21:00; nothing at all during the short night.
        daylight = {h: 400.0 for h in range(4, 21)}
        night = {h: 0.0 for h in list(range(0, 4)) + list(range(21, 24))}
        above = _par_frame(day, {**daylight, **night})
        canopy = _par_frame(day, {**{h: v * 0.7 for h, v in daylight.items()}, **night})

        lamp = derive_lamp_model(above, canopy)
        assert not lamp.is_lighting
        assert lamp.hours_on == frozenset()

        forecast = MockDailyForecast(day)
        predicted = compute_daily_predicted_dli([forecast], {day: 42.0}, lamp)
        assert predicted[day] == pytest.approx(42.0)

    def test_night_lamps_are_measured_and_added(self):
        """A winter schedule: lamps run in the dark, and that power is added."""
        day = date(2026, 1, 15)
        lamp_par = LAMP_THRESHOLD * 3
        readings = {h: 0.0 for h in range(24)}
        readings.update({h: 500.0 for h in range(9, 16)})  # short daylight
        above = _par_frame(day, readings)
        canopy_readings = {h: v * 0.7 for h, v in readings.items()}
        canopy_readings.update({h: lamp_par for h in (4, 5, 6)})  # lamps before dawn
        canopy = _par_frame(day, canopy_readings)

        lamp = derive_lamp_model(above, canopy)
        assert lamp.is_lighting
        assert lamp.hours_on == frozenset({4, 5, 6})
        assert lamp.power_par == pytest.approx(lamp_par)

        forecast = MockDailyForecast(day)
        predicted = compute_daily_predicted_dli([forecast], {day: 5.0}, lamp)
        expected_lamp_dli = 3 * lamp_par * SECONDS_PER_HOUR / UMOL_TO_MOL
        assert predicted[day] == pytest.approx(5.0 + expected_lamp_dli)

    def test_predicted_is_never_below_natural(self):
        day = date(2026, 3, 1)
        forecast = MockDailyForecast(day)
        lamp = LampModel(0.8, 5, 160.0, frozenset({4, 5}), observed_days=14)
        assert compute_daily_predicted_dli([forecast], {day: 12.0}, lamp)[day] > 12.0


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
