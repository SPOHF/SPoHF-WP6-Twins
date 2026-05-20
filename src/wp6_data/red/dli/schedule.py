"""Schedule analysis functions for DLI predictions."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from wp6_data.red.dli.calculator import calculate_hourly_par, estimate_hourly_natural_par
from wp6_data.red.dli.constants import READING_INTERVAL_SECONDS, SECONDS_PER_HOUR, UMOL_TO_MOL

if False:  # TYPE_CHECKING
    from wp6_data.red.dli.model import TwoStageLightModel
    from wp6_data.shared.weather import DailyForecast, OpenMeteoClient


async def fetch_weather_for_range(
    client: OpenMeteoClient,
    start_date: date,
    end_date: date,
) -> list[DailyForecast]:
    """Fetch weather data for a date range, combining archive and forecast APIs.

    Uses historical archive for past dates and forecast API for today/future.

    Args:
        client: OpenMeteo API client
        start_date: Start of range (inclusive)
        end_date: End of range (inclusive)

    Returns:
        List of DailyForecast objects covering the range
    """
    today = date.today()
    forecasts: list[DailyForecast] = []

    # Fetch historical weather for past dates
    if start_date < today:
        hist_end = min(end_date, today - timedelta(days=1))
        historical = await client.get_historical(start_date, hist_end)
        forecasts.extend(historical)

    # Fetch forecast for today and future dates
    if end_date >= today:
        all_forecasts = await client.get_forecast(days=14)
        for f in all_forecasts:
            if f.date >= today and start_date <= f.date <= end_date:
                forecasts.append(f)

    return forecasts


def predict_natural_dli_from_weather(
    model: TwoStageLightModel,
    forecasts: list[DailyForecast],
) -> dict[date, float]:
    """Predict natural DLI for each day from weather forecasts.

    Args:
        model: Trained two-stage light model
        forecasts: List of daily weather forecasts

    Returns:
        Dict mapping date to predicted natural DLI (mol/m²/day)
    """
    return {f.date: model.predict_dli(f.total_radiation) for f in forecasts}


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
            # Assuming ~10min intervals
            par_sum = grp["par"].sum()
            dli = par_sum * READING_INTERVAL_SECONDS / UMOL_TO_MOL
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


_MIN_HOURS_FOR_LAMP_INFERENCE = 6


def try_infer_lamp_from_day(
    par_df: pd.DataFrame,
    target_date: date,
    forecast_by_date: dict[date, object],
    model: object,
) -> dict[int, float] | None:
    """Try to infer a lamp schedule from a specific day's actual PAR data.

    Returns None if insufficient data or no weather available for that day.
    """
    if par_df.empty:
        return None

    par_copy = par_df.copy()
    par_copy["time"] = pd.to_datetime(par_copy["time"], utc=True)
    day_mask = par_copy["time"].dt.date == target_date
    day_df = par_copy[day_mask]

    if day_df.empty:
        return None

    hourly_df = calculate_hourly_par(day_df)
    if len(hourly_df) < _MIN_HOURS_FOR_LAMP_INFERENCE:
        return None

    forecast = forecast_by_date.get(target_date)
    if forecast is None:
        return None

    natural_dli = model.predict_dli(forecast.total_radiation)
    return infer_lamp_schedule_hourly(
        hourly_df, natural_dli, forecast.hourly, forecast.total_radiation
    )


def build_lamp_schedules(
    par_df: pd.DataFrame,
    forecasts: list,
    forecast_by_date: dict[date, object],
    model: object,
    seed_schedule: dict[int, float],
    lamp_ref_day: date,
) -> tuple[dict[date, dict[int, float]], dict[int, float]]:
    """Build per-day lamp schedules iteratively from previous day's data.

    Returns (lamp_schedules, last_good_schedule).
    """
    lamp_schedules: dict[date, dict[int, float]] = {}
    last_good_schedule = seed_schedule

    for forecast in forecasts:
        d = forecast.date
        prev_day = d - timedelta(days=1)

        if prev_day != lamp_ref_day:
            inferred = try_infer_lamp_from_day(
                par_df, prev_day, forecast_by_date, model
            )
            if inferred is not None:
                last_good_schedule = inferred

        lamp_schedules[d] = last_good_schedule

    return lamp_schedules, last_good_schedule


def compute_daily_predicted_dli(
    forecasts: list,
    natural_dli: dict[date, float],
    lamp_schedules: dict[date, dict[int, float]],
    fallback_schedule: dict[int, float],
) -> dict[date, float]:
    """Compute predicted total DLI per day (natural + lamp)."""
    result: dict[date, float] = {}
    for f in forecasts:
        nat = natural_dli.get(f.date, 0.0)
        lamp_sched = lamp_schedules.get(f.date, fallback_schedule)
        lamp_dli = (
            sum(lamp_sched.get(h.datetime.hour, 0.0) for h in f.hourly)
            * SECONDS_PER_HOUR
            / UMOL_TO_MOL
        )
        result[f.date] = nat + lamp_dli
    return result
