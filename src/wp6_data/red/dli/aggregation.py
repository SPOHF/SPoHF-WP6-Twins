"""Aggregation utilities for DLI data processing."""

import numpy as np
import pandas as pd

from wp6_data.red.dli.constants import MIN_INDOOR_PAR, MIN_OUTDOOR_LUX


def encode_day_of_year(day: int) -> tuple[float, float]:
    """Encode day of year as cyclical sin/cos features.

    Args:
        day: Day of year (1-365)

    Returns:
        Tuple of (sin, cos) encoding that handles year wrap-around
    """
    angle = 2 * np.pi * day / 365
    return float(np.sin(angle)), float(np.cos(angle))


def add_day_of_year_features(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Add cyclical day-of-year features (sin/cos encoding) to DataFrame.

    Args:
        df: DataFrame with a date column
        date_col: Name of the date column

    Returns:
        DataFrame with added day_of_year_sin and day_of_year_cos columns
    """
    df = df.copy()
    day_of_year = pd.to_datetime(df[date_col]).dt.dayofyear
    df["day_of_year_sin"] = np.sin(2 * np.pi * day_of_year / 365)
    df["day_of_year_cos"] = np.cos(2 * np.pi * day_of_year / 365)
    return df


def aggregate_to_daily(
    df: pd.DataFrame,
    time_col: str,
    agg_dict: dict[str, str],
    rename_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Aggregate time-series data to daily totals/averages.

    Args:
        df: DataFrame with time-series data
        time_col: Name of the datetime column
        agg_dict: Mapping of column names to aggregation functions
        rename_map: Optional mapping to rename columns after aggregation

    Returns:
        DataFrame aggregated to daily with date column
    """
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df["date"] = df[time_col].dt.date

    daily = df.groupby("date").agg(agg_dict).reset_index()

    if rename_map:
        daily = daily.rename(columns=rename_map)

    return daily


def align_daily_dataframes(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_time_col: str,
    right_time_col: str,
    left_agg: dict[str, str],
    right_agg: dict[str, str],
    left_rename: dict[str, str] | None = None,
    right_rename: dict[str, str] | None = None,
    min_left_value: float | None = None,
    min_left_col: str | None = None,
    min_right_value: float | None = None,
    min_right_col: str | None = None,
) -> pd.DataFrame:
    """Align and aggregate two DataFrames to daily totals, then merge.

    Args:
        left: Left DataFrame
        right: Right DataFrame
        left_time_col: Name of datetime column in left DataFrame
        right_time_col: Name of datetime column in right DataFrame
        left_agg: Aggregation dict for left DataFrame
        right_agg: Aggregation dict for right DataFrame
        left_rename: Column rename mapping for left after aggregation
        right_rename: Column rename mapping for right after aggregation
        min_left_value: Minimum value filter for left DataFrame
        min_left_col: Column to apply min_left_value filter
        min_right_value: Minimum value filter for right DataFrame
        min_right_col: Column to apply min_right_value filter

    Returns:
        Merged DataFrame with aligned daily data
    """
    left_daily = aggregate_to_daily(left, left_time_col, left_agg, left_rename)
    right_daily = aggregate_to_daily(right, right_time_col, right_agg, right_rename)

    merged = left_daily.merge(right_daily, on="date", how="inner")

    if merged.empty:
        return merged

    if min_left_value is not None and min_left_col is not None:
        merged = merged[merged[min_left_col] > min_left_value]

    if min_right_value is not None and min_right_col is not None:
        merged = merged[merged[min_right_col] > min_right_value]

    return merged


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
