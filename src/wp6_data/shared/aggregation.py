"""Generic time-series aggregation utilities.

Extracted from red/dli/aggregation.py for cross-twin reuse.
"""

import numpy as np
import pandas as pd


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
