"""Tests for the GDD (Growing Degree Day) calculator."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from wp6_data.blue import gdd as gdd_mod
from wp6_data.blue.gdd import (
    DEFAULT_BASE_TEMP,
    calculate_daily_gdd,
    cumulative_gdd_from_biofix,
    get_weather_hours,
)
from wp6_data.shared.weather import DailyForecast, HourlyWeather


def _make_readings(temps: list[tuple[str, float]]) -> pd.DataFrame:
    """Create a readings DataFrame from (iso_time, value) pairs."""
    return pd.DataFrame(
        [{"time": pd.Timestamp(t, tz="UTC"), "value": v} for t, v in temps],
    )


def _forecast_day(d: date, temps: list[float]) -> DailyForecast:
    """A DailyForecast with one HourlyWeather per temp (hours 0,6,12,...)."""
    hourly = [
        HourlyWeather(
            datetime=datetime(d.year, d.month, d.day, i * 12, tzinfo=UTC),
            solar_radiation=0.0, cloud_cover=0.0, temperature=t,
        )
        for i, t in enumerate(temps)
    ]
    return DailyForecast(date=d, hourly=hourly)


class _FakeOpenMeteo:
    """Stand-in for OpenMeteoClient: archive ends before `today`, forecast
    supplies the bridge (past_days, overlapping the archive tail) + future."""

    instances = 0

    def __init__(self, latitude: float, longitude: float, **_: object) -> None:
        type(self).instances += 1

    async def get_historical(self, start: date, end: date) -> list[DailyForecast]:
        # 06-01 .. 06-07 — archive lags, stops 5 days before `today` (06-12).
        return [_forecast_day(date(2026, 6, d), [10.0, 20.0]) for d in range(1, 8)]

    async def get_forecast(
        self, days: int = 7, past_days: int = 0,
    ) -> list[DailyForecast]:
        out = []
        # bridge: 06-05 .. 06-12 (overlaps archive on 06-05..07, distinct temps)
        for d in range(5, 13):
            out.append(_forecast_day(date(2026, 6, d), [11.0, 21.0]))
        # future: 06-13 .. 06-12+days
        for i in range(1, days + 1):
            out.append(_forecast_day(date(2026, 6, 12) + timedelta(days=i),
                                     [12.0, 22.0]))
        return out

    async def close(self) -> None:
        return None


class TestGetWeatherHours:
    LAT, LON = 51.40642, 6.11714
    TODAY = date(2026, 6, 12)

    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch):
        gdd_mod._weather_cache.clear()
        _FakeOpenMeteo.instances = 0
        monkeypatch.setattr(gdd_mod, "OpenMeteoClient", _FakeOpenMeteo)

    async def test_actual_is_time_value_up_to_today(self):
        actual, _future = await get_weather_hours(self.LAT, self.LON, self.TODAY)
        assert list(actual.columns) == ["time", "value"]
        assert not actual.empty
        # Archive start present, nothing past today.
        assert actual["time"].min().date() == date(2026, 6, 1)
        assert actual["time"].max().date() == self.TODAY

    async def test_archive_wins_on_overlap_bridge_fills_gap(self):
        actual, _ = await get_weather_hours(self.LAT, self.LON, self.TODAY)
        at = dict(zip(actual["time"], actual["value"], strict=True))
        # 06-05 noon is in BOTH archive (20.0) and bridge (21.0) → archive wins.
        assert at[pd.Timestamp("2026-06-05 12:00", tz="UTC")] == 20.0
        # 06-10 is archive-missing → filled from the bridge (21.0).
        assert at[pd.Timestamp("2026-06-10 12:00", tz="UTC")] == 21.0

    async def test_future_is_strictly_after_today(self):
        _actual, future = await get_weather_hours(self.LAT, self.LON, self.TODAY)
        assert {f.date for f in future} == {
            self.TODAY + timedelta(days=i) for i in range(1, gdd_mod.FORECAST_DAYS + 1)
        }
        assert all(f.date > self.TODAY for f in future)

    async def test_cached_per_location(self):
        await get_weather_hours(self.LAT, self.LON, self.TODAY)
        await get_weather_hours(self.LAT, self.LON, self.TODAY)
        assert _FakeOpenMeteo.instances == 1  # second call served from cache


class TestCalculateDailyGdd:
    def test_basic_gdd(self):
        """A day with min=5, max=25 → avg=15, GDD=15-0=15."""
        df = _make_readings([
            ("2026-04-15T06:00", 5.0),
            ("2026-04-15T14:00", 25.0),
        ])
        result = calculate_daily_gdd(df, base_temp=DEFAULT_BASE_TEMP)
        assert len(result) == 1
        assert result.iloc[0]["t_min"] == 5.0
        assert result.iloc[0]["t_max"] == 25.0
        assert result.iloc[0]["daily_gdd"] == pytest.approx(
            15.0 - DEFAULT_BASE_TEMP,
        )

    def test_below_base_gives_zero(self):
        """All temps below base → GDD = 0."""
        # avg = -3.0, below any non-negative base → clamped to 0
        df = _make_readings([
            ("2026-01-15T06:00", -6.0),
            ("2026-01-15T14:00", 0.0),
        ])
        result = calculate_daily_gdd(df, base_temp=DEFAULT_BASE_TEMP)
        assert result.iloc[0]["daily_gdd"] == 0.0

    def test_cumulative_across_days(self):
        """Cumulative GDD sums correctly across multiple days."""
        df = _make_readings([
            # Day 1: avg = 15, GDD = 15 - base
            ("2026-04-15T06:00", 5.0),
            ("2026-04-15T14:00", 25.0),
            # Day 2: avg = 20, GDD = 20 - base
            ("2026-04-16T06:00", 15.0),
            ("2026-04-16T14:00", 25.0),
        ])
        result = calculate_daily_gdd(df, base_temp=DEFAULT_BASE_TEMP)
        assert len(result) == 2
        day1 = 15.0 - DEFAULT_BASE_TEMP
        day2 = 20.0 - DEFAULT_BASE_TEMP
        assert result.iloc[0]["cumulative_gdd"] == pytest.approx(day1)
        assert result.iloc[1]["cumulative_gdd"] == pytest.approx(day1 + day2)

    def test_custom_base_temp(self):
        """Different base temperature changes GDD values."""
        df = _make_readings([
            ("2026-04-15T06:00", 5.0),
            ("2026-04-15T14:00", 25.0),
        ])
        # base 7.2°C → avg 15 - 7.2 = 7.8
        result = calculate_daily_gdd(df, base_temp=7.2)
        assert result.iloc[0]["daily_gdd"] == pytest.approx(7.8)

    def test_empty_dataframe(self):
        """Empty input returns empty DataFrame with correct columns."""
        df = pd.DataFrame(columns=["time", "value"])
        result = calculate_daily_gdd(df)
        assert result.empty
        assert "cumulative_gdd" in result.columns

    def test_many_readings_per_day(self):
        """Multiple readings per day → uses actual min and max."""
        df = _make_readings([
            ("2026-04-15T00:00", 8.0),
            ("2026-04-15T06:00", 6.0),  # min
            ("2026-04-15T10:00", 14.0),
            ("2026-04-15T14:00", 22.0),  # max
            ("2026-04-15T18:00", 16.0),
            ("2026-04-15T22:00", 10.0),
        ])
        result = calculate_daily_gdd(df, base_temp=DEFAULT_BASE_TEMP)
        assert result.iloc[0]["t_min"] == 6.0
        assert result.iloc[0]["t_max"] == 22.0
        # avg = (6 + 22) / 2 = 14
        assert result.iloc[0]["daily_gdd"] == pytest.approx(
            14.0 - DEFAULT_BASE_TEMP,
        )


class TestCumulativeGddFromBiofix:
    def test_filters_before_biofix(self):
        """Only includes days on or after the biofix date."""
        df = _make_readings([
            ("2026-04-10T06:00", 5.0),
            ("2026-04-10T14:00", 25.0),
            ("2026-04-15T06:00", 5.0),
            ("2026-04-15T14:00", 25.0),
            ("2026-04-16T06:00", 15.0),
            ("2026-04-16T14:00", 25.0),
        ])
        daily = calculate_daily_gdd(df, base_temp=DEFAULT_BASE_TEMP)
        result = cumulative_gdd_from_biofix(daily, biofix=date(2026, 4, 15))
        assert len(result) == 2
        assert result.iloc[0]["date"] == date(2026, 4, 15)
        # Cumulative resets from biofix
        day1 = 15.0 - DEFAULT_BASE_TEMP
        day2 = 20.0 - DEFAULT_BASE_TEMP
        assert result.iloc[0]["cumulative_gdd"] == pytest.approx(day1)
        assert result.iloc[1]["cumulative_gdd"] == pytest.approx(day1 + day2)

    def test_biofix_after_all_data(self):
        """Biofix after all data returns empty."""
        df = _make_readings([
            ("2026-04-10T06:00", 5.0),
            ("2026-04-10T14:00", 25.0),
        ])
        daily = calculate_daily_gdd(df)
        result = cumulative_gdd_from_biofix(daily, biofix=date(2026, 5, 1))
        assert result.empty

    def test_empty_input(self):
        """Empty daily df returns empty."""
        empty = pd.DataFrame(
            columns=["date", "t_min", "t_max", "t_avg", "daily_gdd", "cumulative_gdd"],
        )
        result = cumulative_gdd_from_biofix(empty, biofix=date(2026, 1, 1))
        assert result.empty
