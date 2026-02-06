"""Schedule analysis functions for DLI predictions."""

from datetime import date

import pandas as pd

from wp6_data.red.dli.calculator import estimate_hourly_natural_par
from wp6_data.red.dli.constants import SECONDS_PER_HOUR, UMOL_TO_MOL


def infer_lamp_schedule_hourly(
    actual_hourly_df: pd.DataFrame,
    natural_dli: float,
    hourly_forecasts: list,
    total_radiation: float,
) -> dict[int, float]:
    """Infer lamp schedule from actual vs predicted natural light.

    Args:
        actual_hourly_df: Hourly PAR averages with datetime and par_avg columns
        natural_dli: Predicted daily natural DLI
        hourly_forecasts: List of hourly forecast objects with datetime and solar_radiation
        total_radiation: Total daily solar radiation

    Returns:
        Dict mapping hour (0-23) to inferred lamp PAR contribution
    """
    inferred_lamp_hourly: dict[int, float] = {}

    for h in hourly_forecasts:
        hour = h.datetime.hour
        natural_par = estimate_hourly_natural_par(
            natural_dli, h.solar_radiation, total_radiation
        )

        # Get actual PAR for this hour
        hour_data = actual_hourly_df[actual_hourly_df["datetime"].dt.hour == hour]
        actual_par = hour_data["par_avg"].iloc[0] if not hour_data.empty else 0.0

        # Infer lamp contribution (clamp to 0)
        inferred_lamp_hourly[hour] = max(0.0, actual_par - natural_par)

    return inferred_lamp_hourly


def distribute_dli_across_hours(
    daily_dli: float,
    hourly_forecasts: list,
    total_radiation: float,
) -> dict[int, float]:
    """Distribute daily DLI across hours proportionally to solar radiation.

    Args:
        daily_dli: Total daily DLI to distribute
        hourly_forecasts: List of hourly forecast objects with datetime and solar_radiation
        total_radiation: Total daily solar radiation

    Returns:
        Dict mapping hour (0-23) to PAR value
    """
    hourly_par: dict[int, float] = {}

    for h in hourly_forecasts:
        hour = h.datetime.hour
        hourly_par[hour] = estimate_hourly_natural_par(
            daily_dli, h.solar_radiation, total_radiation
        )

    return hourly_par


def prepare_daily_dli_summary(
    actual_df: pd.DataFrame | None,
    predicted_df: pd.DataFrame | None,
    natural_df: pd.DataFrame | None,
) -> dict[date, dict]:
    """Prepare daily DLI summary from actual, predicted, and natural DataFrames.

    Args:
        actual_df: DataFrame with actual PAR readings (datetime, par columns)
        predicted_df: DataFrame with predicted PAR (datetime, par columns)
        natural_df: DataFrame with natural PAR predictions (datetime, par columns)

    Returns:
        Dict mapping dates to {actual, predicted, natural} DLI values
    """
    daily_dli: dict[date, dict] = {}

    # Process actual data
    if actual_df is not None and not actual_df.empty:
        actual_df = actual_df.copy()
        actual_df["date"] = pd.to_datetime(actual_df["datetime"]).dt.date
        for d, grp in actual_df.groupby("date"):
            # Sum PAR readings and convert to DLI
            # Assuming ~10min intervals = 600 seconds
            par_sum = grp["par"].sum()
            dli = par_sum * 600 / UMOL_TO_MOL
            daily_dli.setdefault(d, {})["actual"] = dli

    # Process predicted data
    if predicted_df is not None and not predicted_df.empty:
        predicted_df = predicted_df.copy()
        predicted_df["date"] = pd.to_datetime(predicted_df["datetime"]).dt.date
        for d, grp in predicted_df.groupby("date"):
            dli = grp["par"].sum() * SECONDS_PER_HOUR / UMOL_TO_MOL
            daily_dli.setdefault(d, {})["predicted"] = dli

    # Process natural data
    if natural_df is not None and not natural_df.empty:
        natural_df = natural_df.copy()
        natural_df["date"] = pd.to_datetime(natural_df["datetime"]).dt.date
        for d, grp in natural_df.groupby("date"):
            dli = grp["par"].sum() * SECONDS_PER_HOUR / UMOL_TO_MOL
            daily_dli.setdefault(d, {})["natural"] = dli

    return daily_dli


def estimate_remaining_dli(
    predicted_df: pd.DataFrame,
    target_date: date,
    current_hour: int,
) -> float:
    """Estimate remaining DLI for today based on predicted values.

    Args:
        predicted_df: DataFrame with predicted PAR (datetime, par columns)
        target_date: Date to calculate remaining DLI for
        current_hour: Current hour (0-23)

    Returns:
        Remaining DLI from current_hour to end of day
    """
    if predicted_df is None or predicted_df.empty:
        return 0.0

    predicted_df = predicted_df.copy()
    predicted_df["date"] = pd.to_datetime(predicted_df["datetime"]).dt.date

    today_predicted = predicted_df[predicted_df["date"] == target_date]
    if today_predicted.empty:
        return 0.0

    remaining = today_predicted[
        pd.to_datetime(today_predicted["datetime"]).dt.hour > current_hour
    ]
    remainder_dli = remaining["par"].sum() * SECONDS_PER_HOUR / UMOL_TO_MOL

    return remainder_dli
