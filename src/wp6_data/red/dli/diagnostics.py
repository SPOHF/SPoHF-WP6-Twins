"""Diagnostic functions for DLI model analysis."""

import numpy as np
import pandas as pd


def align_weather_outdoor_hourly(
    weather_df: pd.DataFrame,
    outdoor_df: pd.DataFrame,
    min_lux: float = 10.0,
    min_radiation: float = 0.0,
) -> pd.DataFrame:
    """Align weather and outdoor data at hourly granularity.

    Args:
        weather_df: Weather data with datetime, solar_radiation columns
        outdoor_df: Outdoor sensor data with time, lux columns
        min_lux: Minimum lux value to include
        min_radiation: Minimum radiation value to include

    Returns:
        Merged DataFrame at hourly granularity
    """
    weather = weather_df.copy()
    outdoor = outdoor_df.copy()

    weather["datetime"] = pd.to_datetime(weather["datetime"], utc=True)
    weather["hour_key"] = weather["datetime"].dt.floor("h")

    outdoor["time"] = pd.to_datetime(outdoor["time"], utc=True)
    outdoor["hour_key"] = outdoor["time"].dt.floor("h")
    outdoor_hourly = outdoor.groupby("hour_key").agg({"lux": "mean"}).reset_index()

    merged = weather.merge(outdoor_hourly, on="hour_key", how="inner")
    merged = merged[merged["lux"] > min_lux]

    if min_radiation > 0 and "solar_radiation" in merged.columns:
        merged = merged[merged["solar_radiation"] > min_radiation]

    return merged


def calculate_correlation_comparison(
    merged_df: pd.DataFrame,
    x_col: str,
    y_col: str,
) -> dict:
    """Calculate correlation at hourly and daily aggregation levels.

    Args:
        merged_df: Merged DataFrame with x_col and y_col
        x_col: Name of x column
        y_col: Name of y column

    Returns:
        Dict with hourly_corr, daily_corr, hourly_samples, daily_samples
    """
    if merged_df.empty:
        return {
            "hourly_corr": 0.0,
            "daily_corr": 0.0,
            "hourly_samples": 0,
            "daily_samples": 0,
        }

    # Hourly correlation
    hourly_corr = merged_df[x_col].corr(merged_df[y_col])
    hourly_samples = len(merged_df)

    # Daily aggregation and correlation
    df = merged_df.copy()
    df["date"] = df["hour_key"].dt.date
    daily_agg = df.groupby("date").agg({x_col: "sum", y_col: "sum"}).reset_index()
    daily_corr = daily_agg[x_col].corr(daily_agg[y_col])
    daily_samples = len(daily_agg)

    return {
        "hourly_corr": float(hourly_corr) if pd.notna(hourly_corr) else 0.0,
        "daily_corr": float(daily_corr) if pd.notna(daily_corr) else 0.0,
        "hourly_samples": hourly_samples,
        "daily_samples": daily_samples,
    }


def analyze_reporting_frequency(
    df: pd.DataFrame,
    time_col: str = "time",
) -> dict:
    """Analyze reporting frequency of sensor data.

    Args:
        df: DataFrame with time-series data
        time_col: Name of the datetime column

    Returns:
        Dict with median_interval_minutes, readings_per_hour,
        days_with_few_readings, total_days
    """
    if len(df) < 2:
        return {
            "median_interval_minutes": 0.0,
            "readings_per_hour": 0.0,
            "days_with_few_readings": 0,
            "total_days": 0,
        }

    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.sort_values(time_col)

    # Calculate time intervals
    time_diffs = df[time_col].diff().dropna()
    median_interval = time_diffs.median().total_seconds() / 60  # minutes
    readings_per_hour = 60 / median_interval if median_interval > 0 else 0

    # Check for days with few readings
    df["date"] = df[time_col].dt.date
    daily_counts = df.groupby("date").size()
    days_with_few = int((daily_counts < 20).sum())
    total_days = len(daily_counts)

    return {
        "median_interval_minutes": float(median_interval),
        "readings_per_hour": float(readings_per_hour),
        "days_with_few_readings": days_with_few,
        "total_days": total_days,
    }


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
