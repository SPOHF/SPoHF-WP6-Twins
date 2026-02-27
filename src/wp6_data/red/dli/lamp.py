"""Lamp detection and correction for DLI model."""

import numpy as np
import pandas as pd


def derive_daily_lamp_profile(
    above_lamp_df: pd.DataFrame,
    plant_level_df: pd.DataFrame,
    daylight_threshold: float = 5.0,
    lamp_threshold: float = 10.0,
    min_lamp_readings: int = 3,
) -> pd.DataFrame:
    """Derive daily lamp profile from above-lamp and plant-level sensors.

    Uses s2100-01-par (above lamps) to determine sunrise/sunset, then measures lamp power
    from s2100-02-par during lamp-only hours (before sunrise / after sunset).

    Args:
        above_lamp_df: PAR readings from sensor above lamps (s2100-01-par).
            Columns: device, sensor, time, value
        plant_level_df: PAR readings from sensor at plant level (s2100-02-par).
            Columns: device, sensor, time, value
        daylight_threshold: PAR threshold to detect daylight on above-lamp sensor.
        lamp_threshold: Minimum PAR on plant-level sensor to count as lamp-on.
        min_lamp_readings: Minimum lamp-only readings needed; fewer → lamps treated as off.

    Returns:
        DataFrame with columns: date, sunrise, sunset, lamp_start, lamp_end,
        lamp_power_par, n_lamp_only_readings
    """
    above = above_lamp_df.copy()
    plant = plant_level_df.copy()

    above["time"] = pd.to_datetime(above["time"], utc=True)
    plant["time"] = pd.to_datetime(plant["time"], utc=True)

    above["date"] = above["time"].dt.date
    above["hour"] = above["time"].dt.hour
    plant["date"] = plant["time"].dt.date
    plant["hour"] = plant["time"].dt.hour

    # Get unique dates present in both sensors
    common_dates = sorted(set(above["date"]) & set(plant["date"]))

    records = []
    for day in common_dates:
        day_above = above[above["date"] == day]
        day_plant = plant[plant["date"] == day]

        # Determine sunrise/sunset from above-lamp sensor (hourly aggregation)
        hourly_above = day_above.groupby("hour")["value"].mean()
        daylight_hours = hourly_above[hourly_above > daylight_threshold].index.tolist()

        if daylight_hours:
            sunrise = min(daylight_hours)
            sunset = max(daylight_hours)
        else:
            # No daylight detected — entire day is dark (winter edge case)
            sunrise = None
            sunset = None

        # Find lamp-only hours on plant-level sensor: outside daylight, PAR > lamp_threshold
        if sunrise is not None and sunset is not None:
            lamp_only_mask = (
                ((day_plant["hour"] < sunrise) | (day_plant["hour"] > sunset))
                & (day_plant["value"] > lamp_threshold)
            )
        else:
            # No daylight — all hours with PAR above threshold are lamp-only
            lamp_only_mask = day_plant["value"] > lamp_threshold

        lamp_only = day_plant[lamp_only_mask]
        n_lamp_only = len(lamp_only)

        if n_lamp_only >= min_lamp_readings:
            lamp_power_par = float(np.median(lamp_only["value"]))
            lamp_hours = lamp_only["hour"].unique()
            lamp_start = int(min(lamp_hours))
            lamp_end = int(max(lamp_hours))
        else:
            lamp_power_par = None
            lamp_start = None
            lamp_end = None

        records.append({
            "date": day,
            "sunrise": sunrise,
            "sunset": sunset,
            "lamp_start": lamp_start,
            "lamp_end": lamp_end,
            "lamp_power_par": lamp_power_par,
            "n_lamp_only_readings": n_lamp_only,
        })

    return pd.DataFrame(records)


def subtract_lamp_from_sensor(
    plant_level_df: pd.DataFrame,
    lamp_profile: pd.DataFrame,
) -> pd.DataFrame:
    """Subtract lamp contribution from plant-level PAR readings.

    For each reading, looks up that day's lamp profile. If the reading falls during
    lamp-on hours and lamp_power is known, subtracts the lamp power (clamped to 0).

    Args:
        plant_level_df: PAR readings from plant-level sensor (s2100-02-par).
            Columns: device, sensor, time, value
        lamp_profile: Output from derive_daily_lamp_profile().

    Returns:
        DataFrame with same structure, corrected values.
    """
    df = plant_level_df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour

    # Build lookup: date → {lamp_start, lamp_end, lamp_power_par}
    lamp_lookup: dict = {}
    for _, row in lamp_profile.iterrows():
        if row["lamp_power_par"] is not None and pd.notna(row["lamp_power_par"]):
            lamp_lookup[row["date"]] = {
                "lamp_start": row["lamp_start"],
                "lamp_end": row["lamp_end"],
                "lamp_power_par": row["lamp_power_par"],
            }

    # Compute fallback: median of known lamp powers for days without profile
    known_powers = [v["lamp_power_par"] for v in lamp_lookup.values()]
    fallback_power = float(np.median(known_powers)) if known_powers else None

    def correct_value(row):
        day = row["date"]
        hour = row["hour"]
        value = row["value"]

        profile = lamp_lookup.get(day)
        if profile is None:
            if fallback_power is not None:
                # Use fallback but only during common lamp hours
                # Without specific schedule, don't subtract (safer)
                return value
            return value

        lamp_start = profile["lamp_start"]
        lamp_end = profile["lamp_end"]
        lamp_power = profile["lamp_power_par"]

        # Check if reading is during lamp-on hours
        if lamp_start is not None and lamp_end is not None:
            # Lamp schedule can wrap around midnight (e.g., lamp_start=4, lamp_end=22)
            # or be split (lamp_start=18, lamp_end=6 meaning evening + morning)
            if lamp_start <= lamp_end:
                # Simple range: e.g., 4-22
                is_lamp_on = lamp_start <= hour <= lamp_end
            else:
                # Wrapping range: e.g., 18-6 (evening to morning)
                is_lamp_on = hour >= lamp_start or hour <= lamp_end

            if is_lamp_on:
                return max(0.0, value - lamp_power)

        return value

    df["value"] = df.apply(correct_value, axis=1)
    df = df.drop(columns=["date", "hour"])

    return df
