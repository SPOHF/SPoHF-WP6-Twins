"""Tests for the per-hour lamp state grid behind /dli/lamps."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from wp6_data.red.lamp import (
    DAYLIGHT_THRESHOLD,
    LAMP_THRESHOLD,
    LampState,
    lamp_state_grid,
)


def _frame(day: date, values_by_hour: dict[int, float], days: int = 1) -> pd.DataFrame:
    rows = [
        {"time": datetime(d.year, d.month, d.day, hour, tzinfo=UTC), "value": value}
        for d in (day - timedelta(days=o) for o in range(days))
        for hour, value in values_by_hour.items()
    ]
    return pd.DataFrame(rows)


class TestLampStateGrid:
    def _winter_day(self):
        """Short daylight 09-15, lamps 04-06."""
        above = {h: (400.0 if 9 <= h <= 15 else 0.0) for h in range(24)}
        canopy = {h: value * 0.7 for h, value in above.items()}
        canopy.update({h: LAMP_THRESHOLD * 3 for h in (4, 5, 6)})
        return above, canopy

    def test_classifies_lamp_daylight_and_dark(self):
        above, canopy = self._winter_day()
        day = date(2026, 1, 15)
        grid = lamp_state_grid(_frame(day, above), _frame(day, canopy))

        by_hour = grid.set_index("hour")["state"].to_dict()
        assert by_hour[5] == LampState.LIT
        assert by_hour[12] == LampState.DAYLIGHT
        assert by_hour[20] == LampState.DARK

    def test_long_day_has_no_lit_hours(self):
        day = date(2026, 6, 21)
        above = {h: (400.0 if 4 <= h <= 20 else 0.0) for h in range(24)}
        canopy = {h: value * 0.7 for h, value in above.items()}
        grid = lamp_state_grid(_frame(day, above), _frame(day, canopy))
        assert not (grid["state"] == LampState.LIT).any()

    def test_twilight_below_the_lamp_bar_is_not_a_lamp(self):
        """The false positive the bar was raised for: pre-dawn glow, not lighting.

        Needs a real day around it — a lone twilight hour is a day the sensor was
        not measuring, which the grid drops rather than classifies.
        """
        day = date(2026, 9, 15)
        above = {h: (500.0 if 8 <= h <= 17 else 0.0) for h in range(24)}
        above[4] = DAYLIGHT_THRESHOLD - 1
        canopy = {h: v * 0.7 for h, v in above.items()}
        canopy[4] = LAMP_THRESHOLD - 1

        grid = lamp_state_grid(_frame(day, above), _frame(day, canopy))

        assert grid.set_index("hour").loc[4, "state"] == LampState.DARK

    def test_hours_with_one_sensor_silent_are_absent(self):
        day = date(2026, 1, 15)
        readings = {h: (500.0 if 9 <= h <= 15 else 0.0) for h in range(24)}
        above = _frame(day, readings)
        canopy = _frame(day, {h: v * 0.7 for h, v in readings.items() if h < 12})

        grid = lamp_state_grid(above, canopy)

        assert sorted(grid["hour"]) == list(range(12))

    def test_a_day_the_sensor_was_not_measuring_is_dropped_not_drawn_dark(self):
        """Red's PAR sensors were out of the greenhouse for six weeks in 2026.

        A switched-off sensor reports zeros, not nothing, so without this the
        calendar draws solid midsummer night where there is simply no reading.
        """
        real_day = date(2026, 6, 21)
        daylight = {h: (600.0 if 5 <= h <= 20 else 0.0) for h in range(24)}
        off = dict.fromkeys(range(24), 0.0)

        grid = lamp_state_grid(
            pd.concat([_frame(real_day, daylight),
                       _frame(real_day - timedelta(days=1), off)]),
            pd.concat([_frame(real_day, {h: v * 0.7 for h, v in daylight.items()}),
                       _frame(real_day - timedelta(days=1), off)]),
        )

        assert set(grid["date"]) == {real_day}

    def test_empty_inputs_give_an_empty_grid(self):
        empty = pd.DataFrame(columns=["time", "value"])
        grid = lamp_state_grid(empty, empty)
        assert grid.empty
        assert list(grid.columns) == ["date", "hour", "state", "above_par", "canopy_par"]

    def test_carries_the_readings_behind_each_verdict(self):
        above, canopy = self._winter_day()
        day = date(2026, 1, 15)
        grid = lamp_state_grid(_frame(day, above), _frame(day, canopy))
        lit = grid[grid["state"] == LampState.LIT].iloc[0]
        assert lit["canopy_par"] == LAMP_THRESHOLD * 3
        assert lit["above_par"] == 0.0
