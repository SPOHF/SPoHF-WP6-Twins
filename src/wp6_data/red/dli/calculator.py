"""DLI (Daily Light Integral) calculation from PAR sensor data."""

import numpy as np
import pandas as pd


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
        dli = integrated / 1_000_000

        # Calculate average PAR (only during non-zero periods)
        non_zero = par_values[par_values > 0]
        avg_par = float(np.mean(non_zero)) if len(non_zero) > 0 else 0.0

        # Photoperiod: total time where PAR > threshold (e.g., 10 μmol/m²/s)
        threshold = 10
        photoperiod_hours = _photoperiod_seconds(
            par_values,
            time_seconds,
            threshold=threshold,
        ) / 3600.0

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
