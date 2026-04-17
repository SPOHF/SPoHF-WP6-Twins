"""Aggregation utilities for DLI data processing.

Generic functions (aggregate_to_daily, align_daily_dataframes, etc.) live in
shared.aggregation and are re-exported here for backwards compatibility.
"""

import pandas as pd

from wp6_data.red.dli.constants import MIN_INDOOR_PAR, MIN_OUTDOOR_LUX
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


def align_weather_to_outdoor_daily(
    weather_df: pd.DataFrame,
    outdoor_df: pd.DataFrame,
    min_lux: float = MIN_OUTDOOR_LUX,
) -> pd.DataFrame:
    """Align and aggregate OpenMeteo + s1000 data to daily totals.

    Handles both single-radiation (solar_radiation) and multi-radiation
    (direct_radiation, diffuse_radiation) weather data formats.

    Args:
        weather_df: Weather data with datetime, solar_radiation/direct_radiation columns
        outdoor_df: Outdoor sensor data with time, lux columns
        min_lux: Minimum daily lux sum for valid daylight

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
        "solar_radiation": "direct_radiation_sum",
        "direct_radiation": "direct_radiation_sum",
        "diffuse_radiation": "diffuse_radiation_sum",
        "cloud_cover": "cloud_cover_avg",
    }
    weather_daily = weather_daily.rename(columns=rename_map)

    # Aggregate outdoor lux to daily
    outdoor_daily = outdoor.groupby("date").agg({"lux": "sum"}).reset_index()
    outdoor_daily.columns = ["date", "lux_sum"]

    # Merge
    merged = weather_daily.merge(outdoor_daily, on="date", how="inner")

    if merged.empty:
        return merged

    # Filter valid days
    merged = merged[merged["lux_sum"] > min_lux]
    if "direct_radiation_sum" in merged.columns:
        merged = merged[merged["direct_radiation_sum"] > 0]

    return merged


def align_outdoor_to_indoor_daily(
    outdoor_df: pd.DataFrame,
    indoor_df: pd.DataFrame,
    min_lux: float = MIN_OUTDOOR_LUX,
    min_par: float = MIN_INDOOR_PAR,
) -> pd.DataFrame:
    """Align and aggregate s1000 + indoor PAR data to daily totals.

    Args:
        outdoor_df: Outdoor sensor data with time, lux columns
        indoor_df: Indoor PAR sensor data with time/datetime, value/par columns
        min_lux: Minimum daily lux sum for valid daylight
        min_par: Minimum daily PAR sum for valid readings

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

    # Aggregate to daily
    outdoor_daily = outdoor.groupby("date").agg({"lux": "sum"}).reset_index()
    outdoor_daily.columns = ["date", "lux_sum"]

    indoor_daily = indoor.groupby("date").agg({"par": "sum"}).reset_index()
    indoor_daily.columns = ["date", "par_sum"]

    # Merge
    merged = outdoor_daily.merge(indoor_daily, on="date", how="inner")

    if merged.empty:
        return merged

    # Filter valid days
    merged = merged[merged["lux_sum"] > min_lux]
    merged = merged[merged["par_sum"] > min_par]

    return merged
