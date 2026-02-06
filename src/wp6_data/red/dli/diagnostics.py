"""Diagnostic functions for DLI model analysis."""

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
