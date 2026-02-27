"""Tests for wp6_data.red.dli.diagnostics functions."""

import pandas as pd
import pytest

from wp6_data.red.dli.lamp import (
    derive_daily_lamp_profile,
    subtract_lamp_from_sensor,
)


def _make_par_df(device: str, hours: list[int], values: list[float], day: str = "2026-01-15"):
    """Helper to create a PAR DataFrame for a single day."""
    times = [pd.Timestamp(f"{day} {h:02d}:00", tz="UTC") for h in hours]
    return pd.DataFrame({
        "device": [device] * len(times),
        "sensor": ["par"] * len(times),
        "time": times,
        "value": values,
    })


class TestDeriveDailyLampProfile:
    def test_normal_case(self):
        """Lamps on before sunrise and after sunset, daylight in between."""
        hours = list(range(24))
        # Above-lamp sensor: daylight from hour 8-16
        above_values = [0] * 8 + [100, 300, 500, 700, 700, 500, 300, 100, 0] + [0] * 7
        above_df = _make_par_df("s2100-01-par", hours, above_values)

        # Plant-level sensor: lamps add ~50 PAR before sunrise and after sunset
        plant_values = (
            [50, 50, 50, 50, 50, 50, 0, 0]   # hours 0-7: lamps on early, off near sunrise
            + [80, 250, 400, 550, 550, 400, 250, 80]  # hours 8-15: daylight + some lamp
            + [0, 0, 50, 50, 50, 50, 50, 50]  # hours 16-23: lamps on in evening
        )
        plant_df = _make_par_df("s2100-02-par", hours, plant_values)

        result = derive_daily_lamp_profile(above_df, plant_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["sunrise"] == 8
        assert row["sunset"] == 15
        assert row["lamp_power_par"] == pytest.approx(50.0)
        assert row["n_lamp_only_readings"] > 0
        assert row["lamp_start"] is not None
        assert row["lamp_end"] is not None

    def test_no_lamp_only_hours(self):
        """No readings outside daylight above lamp threshold → lamp_power=None."""
        hours = list(range(6, 20))
        # Above-lamp sensor: daylight all provided hours
        above_values = [50 + 50 * i for i in range(14)]
        above_df = _make_par_df("s2100-01-par", hours, above_values)

        # Plant-level sensor: only during daylight hours, no lamp-only data
        plant_values = [40 + 40 * i for i in range(14)]
        plant_df = _make_par_df("s2100-02-par", hours, plant_values)

        result = derive_daily_lamp_profile(above_df, plant_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["lamp_power_par"] is None
        assert row["lamp_start"] is None
        assert row["lamp_end"] is None

    def test_short_lamp_time_treated_as_off(self):
        """Fewer than min_lamp_readings lamp-only readings → lamps treated as off."""
        hours = list(range(24))
        above_values = [0] * 8 + [100, 300, 500, 700, 700, 500, 300, 100, 0] + [0] * 7
        above_df = _make_par_df("s2100-01-par", hours, above_values)

        # Only 1 lamp-only reading (hour 5)
        plant_values = [0] * 5 + [50] + [0] * 2 + [80, 250, 400, 550, 550, 400, 250, 80] + [0] * 8
        plant_df = _make_par_df("s2100-02-par", hours, plant_values)

        result = derive_daily_lamp_profile(above_df, plant_df, min_lamp_readings=3)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["lamp_power_par"] is None

    def test_multiple_days(self):
        """Profile is computed per day."""
        df1_above = _make_par_df("s2100-01-par", [8, 12, 16], [100, 500, 100], "2026-01-15")
        df2_above = _make_par_df("s2100-01-par", [8, 12, 16], [100, 500, 100], "2026-01-16")
        above_df = pd.concat([df1_above, df2_above], ignore_index=True)

        df1_plant = _make_par_df(
            "s2100-02-par", [4, 5, 6, 8, 12, 16, 20, 21, 22],
            [60, 60, 60, 80, 400, 80, 60, 60, 60], "2026-01-15",
        )
        df2_plant = _make_par_df(
            "s2100-02-par", [4, 5, 6, 8, 12, 16, 20, 21, 22],
            [70, 70, 70, 90, 410, 90, 70, 70, 70], "2026-01-16",
        )
        plant_df = pd.concat([df1_plant, df2_plant], ignore_index=True)

        result = derive_daily_lamp_profile(above_df, plant_df)
        assert len(result) == 2
        assert result.iloc[0]["lamp_power_par"] == pytest.approx(60.0)
        assert result.iloc[1]["lamp_power_par"] == pytest.approx(70.0)

    def test_empty_input(self):
        """Empty input DataFrames return empty result."""
        above_df = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        plant_df = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        result = derive_daily_lamp_profile(above_df, plant_df)
        assert result.empty


class TestSubtractLampFromSensor:
    def _make_lamp_profile(self, lamp_power=50.0, lamp_start=4, lamp_end=22):
        """Helper to create a single-day lamp profile."""
        return pd.DataFrame([{
            "date": pd.Timestamp("2026-01-15").date(),
            "sunrise": 8,
            "sunset": 16,
            "lamp_start": lamp_start,
            "lamp_end": lamp_end,
            "lamp_power_par": lamp_power,
            "n_lamp_only_readings": 10,
        }])

    def test_subtracts_during_lamp_hours(self):
        """Values during lamp hours are reduced by lamp_power."""
        plant_df = _make_par_df("s2100-02-par", [5, 6, 12, 20, 21], [80, 60, 300, 80, 60])
        profile = self._make_lamp_profile(lamp_power=50.0, lamp_start=4, lamp_end=22)

        result = subtract_lamp_from_sensor(plant_df, profile)

        # All hours 4-22 have lamps → subtract 50
        assert result["value"].tolist() == pytest.approx([30.0, 10.0, 250.0, 30.0, 10.0])

    def test_clamps_to_zero(self):
        """Subtraction doesn't go below 0."""
        plant_df = _make_par_df("s2100-02-par", [5], [30.0])
        profile = self._make_lamp_profile(lamp_power=50.0, lamp_start=4, lamp_end=22)

        result = subtract_lamp_from_sensor(plant_df, profile)
        assert result["value"].iloc[0] == 0.0

    def test_no_lamp_profile_for_day(self):
        """Days without a lamp profile keep original values."""
        plant_df = _make_par_df("s2100-02-par", [5, 12], [80.0, 300.0], day="2026-01-20")
        # Profile is for Jan 15, not Jan 20
        profile = self._make_lamp_profile()

        result = subtract_lamp_from_sensor(plant_df, profile)
        assert result["value"].tolist() == pytest.approx([80.0, 300.0])

    def test_outside_lamp_hours_unchanged(self):
        """Values outside lamp schedule are not modified."""
        # Lamp hours 18-22 (evening only)
        plant_df = _make_par_df("s2100-02-par", [10, 12, 14], [200.0, 300.0, 200.0])
        profile = self._make_lamp_profile(lamp_power=50.0, lamp_start=18, lamp_end=22)

        result = subtract_lamp_from_sensor(plant_df, profile)
        # Hours 10, 12, 14 are outside 18-22 → unchanged
        assert result["value"].tolist() == pytest.approx([200.0, 300.0, 200.0])

    def test_preserves_dataframe_structure(self):
        """Output has same columns (minus internal helper cols)."""
        plant_df = _make_par_df("s2100-02-par", [5, 12], [80.0, 300.0])
        profile = self._make_lamp_profile()

        result = subtract_lamp_from_sensor(plant_df, profile)
        assert set(result.columns) == {"device", "sensor", "time", "value"}

    def test_none_lamp_power_profile_skipped(self):
        """Days where lamp_power_par is None don't affect values."""
        plant_df = _make_par_df("s2100-02-par", [5, 12], [80.0, 300.0])
        profile = pd.DataFrame([{
            "date": pd.Timestamp("2026-01-15").date(),
            "sunrise": 8,
            "sunset": 16,
            "lamp_start": None,
            "lamp_end": None,
            "lamp_power_par": None,
            "n_lamp_only_readings": 0,
        }])

        result = subtract_lamp_from_sensor(plant_df, profile)
        assert result["value"].tolist() == pytest.approx([80.0, 300.0])

    def test_empty_input(self):
        """Empty sensor data returns empty result."""
        plant_df = pd.DataFrame(columns=["device", "sensor", "time", "value"])
        profile = self._make_lamp_profile()

        result = subtract_lamp_from_sensor(plant_df, profile)
        assert result.empty
