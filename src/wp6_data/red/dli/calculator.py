"""DLI (Daily Light Integral) calculation from PAR sensor data."""

import numpy as np
import pandas as pd


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
        dli = integrated / 1_000_000

        # Calculate average PAR (only during non-zero periods)
        non_zero = par_values[par_values > 0]
        avg_par = float(np.mean(non_zero)) if len(non_zero) > 0 else 0.0

        # Photoperiod: time span where PAR > threshold (e.g., 10 μmol/m²/s)
        threshold = 10
        above_threshold = par_values > threshold
        if above_threshold.any():
            first_idx = np.argmax(above_threshold)
            last_idx = len(above_threshold) - np.argmax(above_threshold[::-1]) - 1
            photoperiod_seconds = time_seconds[last_idx] - time_seconds[first_idx]
            photoperiod_hours = photoperiod_seconds / 3600
        else:
            photoperiod_hours = 0.0

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
