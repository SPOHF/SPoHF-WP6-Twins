"""Aggregation utilities for DLI data processing.

Generic functions (aggregate_to_daily, align_daily_dataframes, etc.) live in
shared.aggregation and are re-exported here for backwards compatibility.
"""

import pandas as pd

from wp6_data.red.dli.calculator import integrate_over_time
from wp6_data.red.dli.constants import (
    MIN_INDOOR_PAR_INTEGRAL,
    MIN_OUTDOOR_LUX_HOURS,
    SECONDS_PER_HOUR,
)
from wp6_data.shared.aggregation import (
    add_day_of_year_features,
    aggregate_to_daily,
    align_daily_dataframes,
    encode_day_of_year,
)

__all__ = [
    "add_day_of_year_features",
    "aggregate_to_daily",
    "align_daily_dataframes",
    "align_outdoor_to_indoor_daily",
    "align_weather_to_outdoor_daily",
    "encode_day_of_year",
]


def _daily_integral(
    frame: pd.DataFrame, value_col: str, *, time_col: str, per_hour: bool = False
) -> pd.DataFrame:
    """Per-day time integral of ``value_col``, as a ``date`` + value frame.

    A daily total has to be an integral over the timestamps, never a sum of
    rows. A sum measures how often the sensor reported: red's s1000 fell from
    ~270 readings a day to 97 in June 2026 with the year's highest mean lux, so
    its summed daily total collapsed to a third on the brightest days — which is
    exactly the signal stage 1 was being asked to learn.
    """
    rows = [
        {
            "date": day,
            value_col: integrate_over_time(
                group[time_col].to_numpy(), group[value_col].to_numpy()
            ) / (SECONDS_PER_HOUR if per_hour else 1.0),
        }
        for day, group in frame.sort_values(time_col).groupby("date")
    ]
    return pd.DataFrame(rows, columns=["date", value_col])


def align_weather_to_outdoor_daily(
    weather_df: pd.DataFrame,
    outdoor_df: pd.DataFrame,
    min_lux: float = MIN_OUTDOOR_LUX_HOURS,
) -> pd.DataFrame:
    """Align and aggregate OpenMeteo + s1000 data to daily totals.

    Handles both single-radiation (solar_radiation) and multi-radiation
    (direct_radiation, diffuse_radiation) weather data formats.

    Args:
        weather_df: Weather data with datetime, solar_radiation/direct_radiation columns
        outdoor_df: Outdoor sensor data with time, lux columns
        min_lux: Minimum daily lux-hours for valid daylight

    Returns:
        Merged DataFrame with daily weather and lux data
    """
    weather = weather_df.copy()
    outdoor = outdoor_df.copy()

    weather["datetime"] = pd.to_datetime(weather["datetime"], utc=True)
    outdoor["time"] = pd.to_datetime(outdoor["time"], utc=True)

    weather["date"] = weather["datetime"].dt.date
    outdoor["date"] = outdoor["time"].dt.date

    # Build aggregation dict based on available columns
    agg_dict: dict[str, str] = {}

    # Global horizontal irradiance, under its own name. The legacy
    # solar_radiation -> direct_radiation_sum rename below is kept for callers
    # that still pass a beam column through the generic slot, but stage 1 asks
    # for shortwave explicitly so it can never be handed a different quantity.
    if "shortwave_radiation" in weather.columns:
        agg_dict["shortwave_radiation"] = "sum"

    if "direct_radiation" in weather.columns:
        agg_dict["direct_radiation"] = "sum"
    elif "solar_radiation" in weather.columns:
        agg_dict["solar_radiation"] = "sum"

    if "diffuse_radiation" in weather.columns:
        agg_dict["diffuse_radiation"] = "sum"
    if "cloud_cover" in weather.columns:
        agg_dict["cloud_cover"] = "mean"

    if not agg_dict:
        raise ValueError("No radiation columns found in weather data")

    weather_daily = weather.groupby("date").agg(agg_dict).reset_index()

    # Rename columns to standard names
    rename_map = {
        "shortwave_radiation": "shortwave_sum",
        "solar_radiation": "direct_radiation_sum",
        "direct_radiation": "direct_radiation_sum",
        "diffuse_radiation": "diffuse_radiation_sum",
        "cloud_cover": "cloud_cover_avg",
    }
    weather_daily = weather_daily.rename(columns=rename_map)

    # Outdoor lux integrated over the day, in lux-hours.
    outdoor_daily = _daily_integral(outdoor, "lux", time_col="time", per_hour=True)
    outdoor_daily.columns = ["date", "lux_hours"]

    # Merge
    merged = weather_daily.merge(outdoor_daily, on="date", how="inner")

    if merged.empty:
        return merged

    # Filter valid days
    merged = merged[merged["lux_hours"] > min_lux]
    if "direct_radiation_sum" in merged.columns:
        merged = merged[merged["direct_radiation_sum"] > 0]

    return merged


def align_outdoor_to_indoor_daily(
    outdoor_df: pd.DataFrame,
    indoor_df: pd.DataFrame,
    min_lux: float = MIN_OUTDOOR_LUX_HOURS,
    min_par: float = MIN_INDOOR_PAR_INTEGRAL,
) -> pd.DataFrame:
    """Align and aggregate s1000 + indoor PAR data to daily totals.

    Args:
        outdoor_df: Outdoor sensor data with time, lux columns
        indoor_df: Indoor PAR sensor data with time/datetime, value/par columns
        min_lux: Minimum daily lux-hours for valid daylight
        min_par: Minimum daily PAR integral (μmol/m²) for valid readings

    Returns:
        Merged DataFrame with daily lux and PAR data
    """
    outdoor = outdoor_df.copy()
    indoor = indoor_df.copy()

    outdoor["time"] = pd.to_datetime(outdoor["time"], utc=True)

    # Handle different column names
    if "time" in indoor.columns:
        indoor["datetime"] = pd.to_datetime(indoor["time"], utc=True)
    else:
        indoor["datetime"] = pd.to_datetime(indoor["datetime"], utc=True)

    if "value" in indoor.columns:
        indoor["par"] = indoor["value"]

    outdoor["date"] = outdoor["time"].dt.date
    indoor["date"] = indoor["datetime"].dt.date

    # Both sides integrated over time, never summed across rows.
    outdoor_daily = _daily_integral(outdoor, "lux", time_col="time", per_hour=True)
    outdoor_daily.columns = ["date", "lux_hours"]

    indoor_daily = _daily_integral(indoor, "par", time_col="datetime")
    indoor_daily.columns = ["date", "par_integral"]

    # Merge
    merged = outdoor_daily.merge(indoor_daily, on="date", how="inner")

    if merged.empty:
        return merged

    # Filter valid days
    merged = merged[merged["lux_hours"] > min_lux]
    merged = merged[merged["par_integral"] > min_par]

    return merged
