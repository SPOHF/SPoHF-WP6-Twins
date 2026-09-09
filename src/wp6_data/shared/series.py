"""A named daily series, and the sparse observations attached to a period.

Both twins ask a provider the same two questions when they draw periods on a
calendar: *what did this environmental series do, day by day*, and *what was
observed, and when*. Neither needs a crop, a treatment or a greenhouse to
express, so the vocabulary lives here rather than in either twin.

A metric is declarative on purpose: pointing one at a different device is a
config edit, never a code change. Red uses that to move a metric onto a
per-height wire device (red ADR 0001); blue to move between a plot's own
sensors and the farm's weather station.

Twin-agnostic by contract (CLAUDE.md).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel, field_validator

from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.twin import SensorDataProvider


class SeriesMetric(BaseModel):
    """One selectable daily series, as a (device, sensor) pair."""

    key: str
    label: str
    unit: str
    device: str
    sensor: str
    agg: str

    @field_validator("agg")
    @classmethod
    def _known_agg(cls, value: str) -> str:
        if value not in CHART_AGG_FUNCS:
            raise ValueError(
                f"unknown agg {value!r}; expected one of {sorted(CHART_AGG_FUNCS)}"
            )
        return value


class PeriodConfig(BaseModel):
    """One declared span of activity, named. ``end`` is exclusive."""

    label: str
    start: date
    end: date


def _bounds(start: date, end: date, timezone: str) -> tuple[datetime, datetime]:
    """The half-open local span as UTC datetimes the provider can take."""
    lo = pd.Timestamp(datetime.combine(start, time.min), tz=timezone)
    hi = pd.Timestamp(datetime.combine(end, time.min), tz=timezone)
    return lo.tz_convert("UTC").to_pydatetime(), hi.tz_convert("UTC").to_pydatetime()


async def daily_series(
    provider: SensorDataProvider,
    metric: SeriesMetric,
    start: date,
    end: date,
    timezone: str,
) -> pd.DataFrame:
    """Daily values for ``metric`` over the half-open span ``[start, end)``.

    Returns columns ``date, value``, one row per day that reported. Days with no
    readings are simply absent rather than zero-filled — a caller turns that
    absence into a coverage fraction (``cycles.exposure``) or a gap in a drawn
    bar, and zero-filling would quietly drag every aggregate towards zero.
    """
    lo, hi = _bounds(start, end, timezone)
    df = await provider.fetch_data(
        device_names=[metric.device],
        sensor_tags=[metric.sensor],
        start=lo, end=hi,
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
    # A day bucket can arrive per device/sensor; collapse defensively so a
    # coverage count stays "days with data", not "rows".
    return out.groupby("date", as_index=False)["value"].mean()


async def observations(
    provider: SensorDataProvider,
    devices: list[str],
    sensor: str,
    start: date,
    end: date,
    timezone: str,
) -> pd.DataFrame:
    """Sparse observations as ``date, device, value`` over ``[start, end)``.

    Unbucketed: these are manual readings anchored at a fixed hour, so a bucket
    would only add a scan. The local date is what a period attaches on.
    """
    lo, hi = _bounds(start, end, timezone)
    df = await provider.fetch_data(
        device_names=devices, sensor_tags=[sensor], start=lo, end=hi,
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
