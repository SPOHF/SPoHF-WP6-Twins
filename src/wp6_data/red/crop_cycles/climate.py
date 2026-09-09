"""Daily climate series for a crop-cycle window.

One function, one shape: given a declared :class:`ClimateMetric` and a date
range, return a tidy ``date, value`` frame of daily values.

This is the wire-ready seam, and it is deliberately *not* a Protocol or a
registry — there is one consumer. It does not need to be, because red already
models wire heights as devices (ADR 0001): pointing a metric at a growth section
means changing the ``device`` in ``metadata.yaml`` to ``WS_01_01-h3``, which
this function serves through exactly the same provider call. The seam is the
config entry, not the code.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared.twin import SensorDataProvider

from .config import ClimateMetric


async def daily_climate(
    provider: SensorDataProvider,
    metric: ClimateMetric,
    start: date,
    end: date,
    timezone: str,
) -> pd.DataFrame:
    """Daily values for ``metric`` over the half-open span ``[start, end)``.

    Returns columns ``date, value``, one row per day that reported. Days with no
    readings are simply absent rather than zero-filled — ``shared.cycles.exposure``
    turns that absence into a coverage fraction, and zero-filling would quietly
    drag every aggregate towards zero.
    """
    start_utc = pd.Timestamp(datetime.combine(start, time.min), tz=timezone)
    end_utc = pd.Timestamp(datetime.combine(end, time.min), tz=timezone)

    df = await provider.fetch_data(
        device_names=[metric.device],
        sensor_tags=[metric.sensor],
        start=start_utc.tz_convert("UTC").to_pydatetime(),
        end=end_utc.tz_convert("UTC").to_pydatetime(),
        bucket=timedelta(days=1),
        agg=metric.agg,
    )
    if df.empty or "time" not in df:
        return pd.DataFrame(columns=["date", "value"])

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["time"], utc=True)
            .dt.tz_convert(timezone)
            .dt.date,
            "value": pd.to_numeric(df["value"], errors="coerce"),
        }
    ).dropna(subset=["value"])
    # A day bucket can arrive per device/sensor; collapse defensively so the
    # exposure coverage count stays "days with data", not "rows".
    return out.groupby("date", as_index=False)["value"].mean()


async def measurements(
    provider: SensorDataProvider,
    devices: list[str],
    sensor: str,
    start: date,
    end: date,
    timezone: str,
) -> pd.DataFrame:
    """Manual measurements as ``date, device, value`` over ``[start, end)``.

    Unbucketed: these are sparse manual readings anchored at a fixed hour, so a
    bucket would only add a scan. The local date is what a cohort attaches on.
    """
    start_utc = pd.Timestamp(datetime.combine(start, time.min), tz=timezone)
    end_utc = pd.Timestamp(datetime.combine(end, time.min), tz=timezone)

    df = await provider.fetch_data(
        device_names=devices,
        sensor_tags=[sensor],
        start=start_utc.tz_convert("UTC").to_pydatetime(),
        end=end_utc.tz_convert("UTC").to_pydatetime(),
    )
    if df.empty or "time" not in df:
        return pd.DataFrame(columns=["date", "device", "value"])

    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["time"], utc=True)
            .dt.tz_convert(timezone)
            .dt.date,
            "device": df["device"],
            "value": pd.to_numeric(df["value"], errors="coerce"),
        }
    ).dropna(subset=["value"])
