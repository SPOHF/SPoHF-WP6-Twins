"""DLI (Daily Light Integral) calculation from PAR sensor data."""

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from wp6_data.red.dli.constants import (
    DEFAULT_PHOTOPERIOD_THRESHOLD,
    SECONDS_PER_HOUR,
    UMOL_TO_MOL,
)


def calculate_dli_trendline(
    dates: Sequence[date],
    values: Sequence[float],
) -> tuple[np.ndarray, float]:
    """Calculate linear trendline for DLI values.

    Args:
        dates: Sequence of dates
        values: Sequence of DLI values corresponding to dates

    Returns:
        Tuple of (trendline_y_values, slope_per_day)
    """
    if len(dates) < 2:
        return np.array([]), 0.0

    x_numeric = np.arange(len(dates))
    coeffs = np.polyfit(x_numeric, values, 1)
    trendline_y = np.polyval(coeffs, x_numeric)
    slope_per_day = float(coeffs[0])

    return trendline_y, slope_per_day


def calculate_lamp_contribution(
    total_dli: float | None,
    natural_dli: float | None,
) -> float | None:
    """Calculate lamp DLI contribution (total - natural).

    Args:
        total_dli: Total DLI including lamps
        natural_dli: Natural light DLI only

    Returns:
        Lamp contribution in DLI, or None if either input is None
    """
    if total_dli is None or natural_dli is None:
        return None
    return total_dli - natural_dli


def estimate_hourly_natural_par(
    daily_dli: float,
    hour_radiation: float,
    total_radiation: float,
) -> float:
    """Estimate natural PAR for a specific hour based on radiation distribution.

    Args:
        daily_dli: Predicted daily DLI (mol/m²/day)
        hour_radiation: Solar radiation for this hour (W/m²)
        total_radiation: Total daily solar radiation (W/m²)

    Returns:
        Estimated PAR in μmol/m²/s for the hour
    """
    if total_radiation <= 0:
        return 0.0

    hour_fraction = hour_radiation / total_radiation
    # Convert DLI to hourly PAR: DLI (mol) * fraction * 1e6 / 3600
    natural_par = (daily_dli * hour_fraction * UMOL_TO_MOL) / SECONDS_PER_HOUR
    return natural_par


def par_sum_to_dli(par_sum: float, seconds_per_reading: float = 600.0) -> float:
    """Convert PAR sum to DLI.

    Args:
        par_sum: Sum of PAR readings (μmol/m²/s summed)
        seconds_per_reading: Seconds per reading interval (default 600 = 10 min)

    Returns:
        DLI in mol/m²/day
    """
    # DLI = par_sum * interval_seconds / 1,000,000
    return (par_sum * seconds_per_reading) / UMOL_TO_MOL


def _photoperiod_seconds(
    par_values: np.ndarray,
    time_seconds: np.ndarray,
    *,
    threshold: float,
) -> float:
    """Return total seconds where PAR is above threshold.

    Uses piecewise-linear interpolation between consecutive samples, so it behaves
    well with gaps and multiple separate "on" periods.
    """
    if len(par_values) < 2:
        return 0.0

    photoperiod = 0.0
    for idx in range(len(par_values) - 1):
        t0 = float(time_seconds[idx])
        t1 = float(time_seconds[idx + 1])
        if t1 <= t0:
            continue

        p0 = float(par_values[idx])
        p1 = float(par_values[idx + 1])

        a0 = p0 > threshold
        a1 = p1 > threshold

        # Fully above threshold
        if a0 and a1:
            photoperiod += t1 - t0
            continue

        # Fully below threshold
        if (not a0) and (not a1):
            continue

        # Crosses the threshold within the interval; assume linear change.
        dp = p1 - p0
        if dp == 0:
            # Flat line exactly at threshold or numerical edge-case.
            continue

        # Fraction of the interval until crossing.
        frac_to_cross = (threshold - p0) / dp
        # Clamp to [0, 1] to be safe with noisy data.
        frac_to_cross = float(np.clip(frac_to_cross, 0.0, 1.0))

        if a0 and (not a1):
            # Above -> below: count time from start until crossing.
            photoperiod += (t1 - t0) * frac_to_cross
        elif (not a0) and a1:
            # Below -> above: count time from crossing until end.
            photoperiod += (t1 - t0) * (1.0 - frac_to_cross)

    return photoperiod


def calculate_daily_dli(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate DLI from PAR readings using trapezoidal integration.

    DLI (mol/m²/day) = ∫PAR(t)dt / 1,000,000
    where PAR is in μmol/m²/s

    Args:
        df: DataFrame with columns: device, sensor, time, value
            where value is PAR in μmol/m²/s

    Returns:
        DataFrame with columns: date, device, dli, avg_par, photoperiod_hours, reading_count
    """
    if df.empty:
        return pd.DataFrame(
            columns=["date", "device", "dli", "avg_par", "photoperiod_hours", "reading_count"]
        )

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["date"] = df["time"].dt.date

    results = []

    for (date_val, device), group in df.groupby(["date", "device"]):
        group = group.sort_values("time")
        par_values = group["value"].values
        times = group["time"].values

        if len(par_values) < 2:
            continue

        # Convert times to seconds from start of day
        time_seconds = (times - times[0]).astype("timedelta64[s]").astype(float)

        # Trapezoidal integration: ∫PAR dt in μmol/m²
        # Then convert to mol/m²/day by dividing by 1,000,000
        integrated = np.trapezoid(par_values, time_seconds)
        dli = integrated / UMOL_TO_MOL

        # Calculate average PAR (only during non-zero periods)
        non_zero = par_values[par_values > 0]
        avg_par = float(np.mean(non_zero)) if len(non_zero) > 0 else 0.0

        # Photoperiod: total time where PAR > threshold
        photoperiod_hours = _photoperiod_seconds(
            par_values,
            time_seconds,
            threshold=DEFAULT_PHOTOPERIOD_THRESHOLD,
        ) / SECONDS_PER_HOUR

        results.append({
            "date": date_val,
            "device": device,
            "dli": round(dli, 2),
            "avg_par": round(avg_par, 1),
            "photoperiod_hours": round(photoperiod_hours, 1),
            "reading_count": len(group),
        })

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values(["date", "device"])
    return result_df


def calculate_hourly_par(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate PAR readings to hourly averages.

    Args:
        df: DataFrame with columns: device, sensor, time, value

    Returns:
        DataFrame with columns: datetime, device, par_avg, par_max, reading_count
    """
    if df.empty:
        return pd.DataFrame(
            columns=["datetime", "device", "par_avg", "par_max", "reading_count"]
        )

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["hour"] = df["time"].dt.floor("h")

    results = []
    for (hour, device), group in df.groupby(["hour", "device"]):
        results.append({
            "datetime": hour,
            "device": device,
            "par_avg": round(group["value"].mean(), 1),
            "par_max": round(group["value"].max(), 1),
            "reading_count": len(group),
        })

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values(["datetime", "device"])
    return result_df
