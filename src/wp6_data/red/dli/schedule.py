"""Schedule analysis functions for DLI predictions."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from wp6_data.red.dli.calculator import estimate_hourly_natural_par
from wp6_data.red.dli.constants import READING_INTERVAL_SECONDS, SECONDS_PER_HOUR, UMOL_TO_MOL
from wp6_data.red.lamp import LampModel

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

    Passes the features stage 1 was *fitted* on. Earlier this handed
    ``total_radiation`` — summed **shortwave**, i.e. direct + diffuse — to the
    ``direct_radiation_sum`` slot, left diffuse at zero and let cloud cover fall
    back to a hardcoded 50%, so two of three weather features were wrong and the
    third was a different physical quantity than the coefficients were fitted on.

    ``day_of_year`` comes from each forecast's own date. Without it the model
    defaulted to *today* for every row, which froze the seasonal term across a
    whole hindcast window.

    Returns:
        Dict mapping date to predicted natural DLI (mol/m²/day)
    """
    return {
        f.date: model.predict_dli(
            f.direct_radiation_sum,
            diffuse_radiation_sum=f.diffuse_radiation_sum,
            cloud_cover_avg=f.avg_cloud_cover,
            day_of_year=f.date.timetuple().tm_yday,
        )
        for f in forecasts
    }


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


def lamp_hourly_par(lamp: LampModel | None) -> dict[int, float]:
    """Lamp PAR per hour-of-day, or a day of zeros when the lamps are not running.

    The single place a ``None`` lamp model (sensors silent, or never derived)
    and a lamp model that is simply *off* collapse to the same thing, so callers
    do not each invent their own empty schedule.
    """
    return lamp.hourly_schedule() if lamp is not None else dict.fromkeys(range(24), 0.0)


def compute_daily_predicted_dli(
    forecasts: list,
    natural_dli: dict[date, float],
    lamp: LampModel | None,
) -> dict[date, float]:
    """Predicted total DLI per day: predicted natural light + the observed lamps.

    The lamp half is *measured* — the level the lamps run at, over the hours they
    have recently been on — never a residual against the natural prediction. When
    the lamps are off, every hour contributes zero and predicted equals natural,
    which is the behaviour a long summer day should show.
    """
    schedule = lamp_hourly_par(lamp)
    return {
        f.date: natural_dli.get(f.date, 0.0)
        + sum(schedule.get(h.datetime.hour, 0.0) for h in f.hourly)
        * SECONDS_PER_HOUR
        / UMOL_TO_MOL
        for f in forecasts
    }
