"""Growing Degree Day (GDD) calculations.

GDD quantifies accumulated heat above a base temperature. Blueberry development
tracks thermal time rather than calendar time, making GDD a better predictor
of phenological stages (bloom, harvest) than calendar dates.

Formula: daily_gdd = max(0, (T_max + T_min) / 2 - T_base)

Reference: Carlson & Hancock (1991), MSU Extension.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from wp6_data.red.dli.weather import DailyForecast

DEFAULT_BASE_TEMP = 5.0  # °C, European convention; biofix = Jan 1
DEFAULT_CHILL_THRESHOLD = 7.2  # °C — hours below this count as chill hours
# hours for Cargo dormancy break; 800–1000h bucket per US PP24,661.
DEFAULT_CHILL_REQUIREMENT = 1000

# Physically plausible range for outdoor air temperature (°C).
# Values outside this range are sensor errors (e.g. 0xFFFFFFFF overflow).
TEMP_MIN_PLAUSIBLE = -40.0
TEMP_MAX_PLAUSIBLE = 60.0


def calculate_daily_gdd(
    df: pd.DataFrame,
    base_temp: float = DEFAULT_BASE_TEMP,
) -> pd.DataFrame:
    """Calculate daily GDD from temperature readings.

    Args:
        df: DataFrame with columns ``time`` (datetime) and ``value`` (temperature °C).
        base_temp: Base temperature below which no growth occurs.

    Returns:
        DataFrame with columns: date, t_min, t_max, t_avg, daily_gdd, cumulative_gdd
    """
    if df.empty:
        return pd.DataFrame(
            columns=["date", "t_min", "t_max", "t_avg", "daily_gdd", "cumulative_gdd"],
        )

    working = df[["time", "value"]].copy()
    working["time"] = pd.to_datetime(working["time"], utc=True)
    # Filter out sensor error values (e.g. 0xFFFFFFFF overflow → 4294967.x)
    working = working[
        working["value"].between(TEMP_MIN_PLAUSIBLE, TEMP_MAX_PLAUSIBLE)
    ]
    working["date"] = working["time"].dt.date
    daily = working.groupby("date").agg(
        t_min=("value", "min"),
        t_max=("value", "max"),
    ).reset_index()

    daily["t_avg"] = (daily["t_max"] + daily["t_min"]) / 2.0
    daily["daily_gdd"] = (daily["t_avg"] - base_temp).clip(lower=0.0)
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["cumulative_gdd"] = daily["daily_gdd"].cumsum()

    return daily


def cumulative_gdd_from_biofix(
    daily_df: pd.DataFrame,
    biofix: date,
) -> pd.DataFrame:
    """Filter daily GDD table to start from a biofix date, recalculate cumulative.

    Args:
        daily_df: Output of :func:`calculate_daily_gdd`.
        biofix: Date to start accumulation (e.g. bloom date).

    Returns:
        Filtered DataFrame with cumulative_gdd recalculated from biofix.
    """
    if daily_df.empty:
        return daily_df

    filtered = daily_df[daily_df["date"] >= biofix].copy()
    if filtered.empty:
        return filtered

    filtered["cumulative_gdd"] = filtered["daily_gdd"].cumsum()
    return filtered.reset_index(drop=True)


def gdd_from_forecasts(
    forecasts: list[DailyForecast],
    base_temp: float = DEFAULT_BASE_TEMP,
    cumulative_start: float = 0.0,
) -> pd.DataFrame:
    """Calculate daily GDD from OpenMeteo forecast objects.

    Args:
        forecasts: List of DailyForecast (from OpenMeteoClient).
        base_temp: Base temperature for GDD calculation.
        cumulative_start: Starting value for cumulative GDD
            (use the last actual cumulative value to continue the curve).

    Returns:
        DataFrame with same columns as calculate_daily_gdd output.
    """
    rows = []
    for fc in forecasts:
        if not fc.hourly:
            continue
        temps = [h.temperature for h in fc.hourly]
        t_min = min(temps)
        t_max = max(temps)
        t_avg = (t_min + t_max) / 2.0
        daily_gdd = max(0.0, t_avg - base_temp)
        rows.append({
            "date": fc.date,
            "t_min": t_min,
            "t_max": t_max,
            "t_avg": t_avg,
            "daily_gdd": daily_gdd,
        })

    if not rows:
        return pd.DataFrame(
            columns=["date", "t_min", "t_max", "t_avg",
                      "daily_gdd", "cumulative_gdd"],
        )

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["cumulative_gdd"] = cumulative_start + df["daily_gdd"].cumsum()
    return df


def calculate_daily_chill_hours(
    df: pd.DataFrame,
    threshold: float = DEFAULT_CHILL_THRESHOLD,
) -> pd.DataFrame:
    """Calculate daily chill hours from temperature readings.

    Chill hours = hours where temperature is below the threshold.
    Estimated from reading intervals: each reading below threshold
    contributes its pro-rata share of the interval.

    Args:
        df: DataFrame with ``time`` (datetime) and ``value`` (°C).
        threshold: Temperature threshold for chilling.

    Returns:
        DataFrame with: date, chill_hours, cumulative_chill
    """
    if df.empty:
        return pd.DataFrame(
            columns=["date", "chill_hours", "cumulative_chill"],
        )

    working = df[["time", "value"]].copy()
    working["time"] = pd.to_datetime(working["time"], utc=True)
    working = working[
        working["value"].between(TEMP_MIN_PLAUSIBLE, TEMP_MAX_PLAUSIBLE)
    ]
    working = working.sort_values("time").reset_index(drop=True)

    # Estimate hours per reading from time gaps
    working["gap_hours"] = (
        working["time"].diff().dt.total_seconds().fillna(0) / 3600
    )
    # Cap gap at 1 hour (avoid inflating from data gaps)
    working["gap_hours"] = working["gap_hours"].clip(upper=1.0)
    working["is_chill"] = working["value"] < threshold
    working["chill_contrib"] = working["gap_hours"] * working["is_chill"]
    working["date"] = working["time"].dt.date

    daily = working.groupby("date").agg(
        chill_hours=("chill_contrib", "sum"),
    ).reset_index()
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["cumulative_chill"] = daily["chill_hours"].cumsum()

    return daily


def chill_hours_for_season(
    daily_chill: pd.DataFrame,
    season_start_month: int = 10,
    season_start_day: int = 1,
    year: int | None = None,
) -> pd.DataFrame:
    """Extract chill hours for a dormancy season (Oct 1 → Mar 31).

    Args:
        daily_chill: Output of :func:`calculate_daily_chill_hours`.
        season_start_month: Month to start counting (default October).
        season_start_day: Day to start counting.
        year: Year of season start (e.g. 2025 for winter 2025-2026).
            Defaults to most recent complete/in-progress season.

    Returns:
        Filtered DataFrame with cumulative_chill recalculated from season start.
    """
    if daily_chill.empty:
        return daily_chill

    if year is None:
        today = date.today()
        year = today.year if today.month >= season_start_month else today.year - 1

    start = date(year, season_start_month, season_start_day)
    end = date(year + 1, 3, 31)  # chilling season ends ~March

    filtered = daily_chill[
        (daily_chill["date"] >= start) & (daily_chill["date"] <= end)
    ].copy()
    if filtered.empty:
        return filtered

    filtered["cumulative_chill"] = filtered["chill_hours"].cumsum()
    return filtered.reset_index(drop=True)
