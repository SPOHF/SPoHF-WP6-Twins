"""`/dli/history` must not read lamp light off the gap between its two sensors.

The page used to label ``NATURAL_LIGHT_SENSOR`` "Natural Light" and
``TOTAL_LIGHT_SENSOR`` "Total Light", and derive a "Lamp DLI" column as
``total - natural``. Both sensors are real, but they hang at different heights:
the first at the roof above the lamps, the second under them at plant level. The
gap between them is therefore dominated by **attenuation**, not by lamps, and on
any sunny lamp-free day it is negative — which drew as the greenhouse's lamps
removing light from the crop.

These tests pin the replacement: the lamp is detected and its measured power
subtracted, so what comes out is light the lamps actually contributed.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from wp6_data.red.dli.constants import (
    NATURAL_LIGHT_SENSOR,
    READING_INTERVAL_SECONDS,
    TOTAL_LIGHT_SENSOR,
)
from wp6_data.red.lamp import LAMP_SUBTRACTION_THRESHOLD
from wp6_data.red.routes.dli.history import _measured_lamp_dli

# Structure between the roof sensor and the canopy. Red measures ~0.63; the exact
# figure is irrelevant here, only that it is well below 1 so the plant-level
# sensor reads *lower* than the one above it on a lamp-free day.
ATTENUATION = 0.63

# Comfortably above LAMP_SUBTRACTION_THRESHOLD, so a lit hour is unambiguous.
LAMP_PAR = 160.0

DAY = datetime(2026, 1, 15, tzinfo=UTC)
# Red's real winter schedule runs across midnight; these are the dark-side hours,
# where the lamp is measurable without any daylight mixed in.
LAMP_HOURS = frozenset({0, 1, 2, 3, 4, 5, 6, 23})
DAYLIGHT_HOURS = frozenset(range(9, 16))


def _frames(*, lamps_on: bool, peak_par: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One day of readings for both sensors, at the real PAR cadence."""
    above_rows, plant_rows = [], []
    steps = 24 * 60 * 60 // READING_INTERVAL_SECONDS

    for step in range(steps + 1):
        t = DAY + timedelta(seconds=step * READING_INTERVAL_SECONDS)
        hour = t.hour if t.date() == DAY.date() else 23

        # Daylight: a flat plateau over the lit hours, dark outside them.
        above_par = peak_par if hour in DAYLIGHT_HOURS else 0.0
        plant_par = above_par * ATTENUATION
        if lamps_on and hour in LAMP_HOURS:
            plant_par += LAMP_PAR

        above_rows.append(
            {"device": NATURAL_LIGHT_SENSOR, "sensor": "par", "time": t, "value": above_par}
        )
        plant_rows.append(
            {"device": TOTAL_LIGHT_SENSOR, "sensor": "par", "time": t, "value": plant_par}
        )

    return pd.DataFrame(above_rows), pd.DataFrame(plant_rows)


def _lamp_dli(above: pd.DataFrame, plant: pd.DataFrame) -> float | None:
    """Run the page's lamp calculation over one day and return that day's value."""
    from wp6_data.red.dli import calculate_daily_dli

    plant_data = calculate_daily_dli(plant)[["date", "dli"]].rename(columns={"dli": "plant_dli"})
    result = _measured_lamp_dli(above, plant, plant_data)
    if result.empty:
        return None
    return float(result["lamp_dli"].iloc[0])


def test_sunny_lamp_free_day_reports_no_lamp_light():
    """The case the old subtraction got backwards: bright sun, lamps off."""
    above, plant = _frames(lamps_on=False, peak_par=800.0)

    assert _lamp_dli(above, plant) == pytest.approx(0.0, abs=0.01)


def test_sunny_lamp_free_day_would_have_been_negative_by_subtraction():
    """Why the old column was wrong, stated as an assertion rather than a claim."""
    from wp6_data.red.dli import calculate_daily_dli

    above, plant = _frames(lamps_on=False, peak_par=800.0)
    above_dli = calculate_daily_dli(above)["dli"].iloc[0]
    plant_dli = calculate_daily_dli(plant)["dli"].iloc[0]

    assert plant_dli - above_dli < 0
    assert _lamp_dli(above, plant) >= 0


def test_lit_winter_day_recovers_the_lamp_contribution():
    """Lamps running through a dim day: the measured lamp DLI is what they added."""
    above, plant = _frames(lamps_on=True, peak_par=100.0)

    lamp_seconds = len(LAMP_HOURS) * 60 * 60
    expected = LAMP_PAR * lamp_seconds / 1_000_000

    assert _lamp_dli(above, plant) == pytest.approx(expected, rel=0.05)


def test_lamp_level_sits_above_the_subtraction_threshold():
    """Guards the fixture, not the code: a dimmer lamp would not be detected."""
    assert LAMP_PAR > LAMP_SUBTRACTION_THRESHOLD


def test_day_without_both_sensors_is_absent_not_zero():
    """A day the profile could not judge must read "-", never "no lamp light"."""
    above, plant = _frames(lamps_on=True, peak_par=100.0)

    assert _measured_lamp_dli(above.iloc[0:0], plant, pd.DataFrame()).empty
    assert _measured_lamp_dli(above, plant.iloc[0:0], pd.DataFrame()).empty
