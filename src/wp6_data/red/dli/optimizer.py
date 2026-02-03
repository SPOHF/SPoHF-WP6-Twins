"""Light schedule optimization based on weather forecasts and target DLI."""

import os
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from wp6_data.red.dli.weather import DailyForecast


@dataclass
class OptimizationParams:
    """Parameters for schedule optimization."""

    target_dli: float = field(
        default_factory=lambda: float(os.getenv("WP6_RED_DLI_TARGET", "25.0"))
    )  # mol/m²/day
    max_photoperiod: float = field(
        default_factory=lambda: float(os.getenv("WP6_RED_DLI_PHOTOPERIOD", "16.0"))
    )  # hours
    max_par: float = field(
        default_factory=lambda: float(os.getenv("WP6_RED_LAMP_MAX_PAR", "800.0"))
    )  # μmol/m²/s lamp capacity
    natural_light_factor: float = field(
        default_factory=lambda: float(os.getenv("WP6_RED_GREENHOUSE_TRANSMISSION", "0.3"))
    )  # transmission into greenhouse
    schedule_sensor: str = field(
        default_factory=lambda: os.getenv("WP6_RED_DLI_SCHEDULE_SENSOR", "s2100-02-par")
    )  # PAR sensor for schedule comparison

    # Lamp scheduling hours (start/end of artificial light window)
    lamp_start_hour: int = 6  # 6 AM
    lamp_end_hour: int = 22  # 10 PM


@dataclass
class HourlySchedule:
    """Optimized schedule for a single hour."""

    datetime: datetime
    lamp_par: float  # Artificial light PAR (μmol/m²/s)
    natural_par: float  # Estimated natural PAR (μmol/m²/s)
    total_par: float  # Combined PAR (μmol/m²/s)
    lamp_intensity: float  # Lamp intensity (0.0 - 1.0)


@dataclass
class OptimizedSchedule:
    """Complete optimized schedule for a day."""

    date: date
    hourly: list[HourlySchedule]
    target_dli: float
    achieved_dli: float
    natural_dli: float
    lamp_dli: float
    lamp_hours: float
    energy_factor: float  # 0-1, where 1 = full lamp usage, 0 = no lamps needed

    @property
    def savings_percent(self) -> float:
        """Calculate energy savings percentage vs running at max all day."""
        if self.target_dli <= 0:
            return 0.0
        # Max theoretical lamp usage = max_par * photoperiod
        return round((1 - self.energy_factor) * 100, 1)


def calculate_optimal_schedule(
    forecast: DailyForecast,
    params: OptimizationParams | None = None,
) -> OptimizedSchedule:
    """Calculate optimal lamp intensity per hour based on weather forecast.

    Strategy:
    1. Estimate natural light contribution from weather data using two-stage model
    2. Determine required supplemental light to reach target DLI
    3. Distribute lamp usage optimally (reduce during high natural light)

    Args:
        forecast: DailyForecast with hourly weather data
        params: Optimization parameters (uses defaults if None)

    Returns:
        OptimizedSchedule with hourly lamp intensities
    """
    if params is None:
        params = OptimizationParams()

    # Get total daily radiation from forecast
    daily_radiation_sum = forecast.total_radiation

    # Use two-stage model for daily DLI prediction
    from wp6_data.red.dli.model import get_model

    model = get_model()

    if model.is_trained() and daily_radiation_sum > 0:
        # Model predicts daily DLI directly from radiation sum
        natural_dli = model.predict_dli(daily_radiation_sum)

        # Distribute DLI across hours proportionally to radiation profile
        hourly_natural: list[tuple[datetime, float]] = []
        for h in forecast.hourly:
            if daily_radiation_sum > 0:
                # Proportion of daily radiation in this hour
                hour_fraction = h.solar_radiation / daily_radiation_sum
                # Convert DLI fraction back to average PAR for this hour
                # DLI (mol/m²/day) = PAR (μmol/m²/s) * 3600s * 24h / 1_000_000
                # So for 1 hour: PAR = DLI_fraction * 1_000_000 / 3600
                hour_dli = natural_dli * hour_fraction
                natural_par = hour_dli * 1_000_000 / 3600
            else:
                natural_par = 0.0
            hourly_natural.append((h.datetime, natural_par))
    else:
        raise RuntimeError("DLI model is not trained or daily radiation is zero.")

    # Calculate target PAR per hour to achieve target DLI over the photoperiod
    # Target DLI spread evenly = target_dli / photoperiod_hours
    # Target hourly PAR = (target_dli / photoperiod_hours) * 1_000_000 / 3600
    lamp_window_hours = params.lamp_end_hour - params.lamp_start_hour
    if lamp_window_hours > 0:
        target_hourly_par = (params.target_dli / lamp_window_hours) * 1_000_000 / 3600
    else:
        target_hourly_par = 0.0

    # Build hourly schedule - lamp complements natural light to reach target PAR
    hourly_schedules: list[HourlySchedule] = []
    total_lamp_par_seconds = 0.0
    lamp_on_hours = 0.0

    for dt, natural_par in hourly_natural:
        hour = dt.hour

        # Only run lamps during allowed window
        lamp_active = params.lamp_start_hour <= hour < params.lamp_end_hour

        if lamp_active:
            # Lamp fills the gap between natural light and target
            lamp_par = max(0, target_hourly_par - natural_par)
            # Cap at lamp capacity
            lamp_par = min(lamp_par, params.max_par)
            total_par = natural_par + lamp_par
            lamp_intensity = lamp_par / params.max_par if params.max_par > 0 else 0.0

            if lamp_par > 0:
                lamp_on_hours += 1
        else:
            lamp_par = 0.0
            lamp_intensity = 0.0
            total_par = natural_par

        total_lamp_par_seconds += lamp_par * 3600

        hourly_schedules.append(
            HourlySchedule(
                datetime=dt,
                lamp_par=round(lamp_par, 1),
                natural_par=round(natural_par, 1),
                total_par=round(total_par, 1),
                lamp_intensity=round(lamp_intensity, 3),
            )
        )

    # Calculate achieved values
    lamp_dli = total_lamp_par_seconds / 1_000_000
    achieved_dli = natural_dli + lamp_dli

    # Energy factor: actual lamp usage vs theoretical max
    max_lamp_seconds = params.max_par * lamp_window_hours * 3600
    energy_factor = total_lamp_par_seconds / max_lamp_seconds if max_lamp_seconds > 0 else 0.0

    return OptimizedSchedule(
        date=forecast.date,
        hourly=hourly_schedules,
        target_dli=params.target_dli,
        achieved_dli=round(achieved_dli, 2),
        natural_dli=round(natural_dli, 2),
        lamp_dli=round(lamp_dli, 2),
        lamp_hours=lamp_on_hours,
        energy_factor=round(energy_factor, 3),
    )


def schedule_to_dataframe(schedule: OptimizedSchedule) -> pd.DataFrame:
    """Convert OptimizedSchedule to DataFrame for charting.

    Returns:
        DataFrame with columns: datetime, lamp_par, natural_par, total_par, lamp_intensity
    """
    records = [
        {
            "datetime": h.datetime,
            "lamp_par": h.lamp_par,
            "natural_par": h.natural_par,
            "total_par": h.total_par,
            "lamp_intensity": h.lamp_intensity,
        }
        for h in schedule.hourly
    ]

    df = pd.DataFrame(records)
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df


def compare_actual_vs_optimal(
    actual_df: pd.DataFrame,
    optimal_schedule: OptimizedSchedule,
) -> dict:
    """Compare actual PAR readings against optimal schedule.

    Args:
        actual_df: DataFrame with columns: datetime, par (actual readings)
        optimal_schedule: The calculated optimal schedule

    Returns:
        Dict with comparison metrics
    """
    if actual_df.empty:
        return {
            "actual_dli": 0.0,
            "optimal_dli": optimal_schedule.achieved_dli,
            "target_dli": optimal_schedule.target_dli,
            "difference": optimal_schedule.achieved_dli,
            "efficiency": 0.0,
        }

    # Calculate actual DLI from readings
    actual_df = actual_df.copy()
    actual_df["datetime"] = pd.to_datetime(actual_df["datetime"], utc=True)
    actual_df = actual_df.sort_values("datetime")

    # Group by hour for comparison
    actual_df["hour"] = actual_df["datetime"].dt.floor("h")
    hourly_avg = actual_df.groupby("hour")["par"].mean()

    # Sum to get approximate DLI
    actual_dli = hourly_avg.sum() * 3600 / 1_000_000

    # Calculate potential savings
    # If actual DLI > optimal, we could have saved energy
    excess_dli = max(0, actual_dli - optimal_schedule.target_dli)

    return {
        "actual_dli": round(actual_dli, 2),
        "optimal_dli": optimal_schedule.achieved_dli,
        "target_dli": optimal_schedule.target_dli,
        "difference": round(actual_dli - optimal_schedule.achieved_dli, 2),
        "excess_dli": round(excess_dli, 2),
        "potential_savings_percent": round(
            (excess_dli / actual_dli * 100) if actual_dli > 0 else 0, 1
        ),
    }
