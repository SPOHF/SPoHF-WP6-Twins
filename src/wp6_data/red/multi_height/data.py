"""Wire-sensor data access and per-day metrics for the red multi-height views."""

from datetime import date

import pandas as pd  # type: ignore[import-untyped]

from .. import deps
from ..db import (
    WIRE_SENSOR_HEIGHTS,
    wire_device_id,
    wire_physical_id,
)
from ..risk.metrics import compute_dli

USE_LATEST_DATE_IN_DATA = False


def wire_ids() -> list[str]:
    """Physical wire ids declared in metadata (devices typed 'wire'), sorted."""
    ids = {
        wire_physical_id(device_id)
        for device_id, meta in deps.metadata.devices.items()
        if meta.type == "wire"
    }
    return sorted(ids)


async def undeclared_wire_ids() -> list[str]:
    """Physical wires reporting into wire_sensors but absent from metadata, sorted.

    Metadata is the source of truth for which wires exist, so every view
    enumerates from it. A wire hung in the greenhouse but never declared would
    therefore write rows that no view ever reads. This surfaces that drift.
    """
    summary = await deps.db.get_wire_device_summary()
    reporting = {wire_physical_id(device_id) for device_id in summary}
    return sorted(reporting - set(wire_ids()))


async def load_wire_sensor_data(start, end):
    """Tidy long wire-sensor readings for a UTC window: time, height, measurement, value."""
    df = await deps.db.get_wire_sensor_readings(start=start, end=end)

    if df.empty:
        return df

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["time", "value"])


### Load data ###
async def load_wire_readings(start=None, end=None):
    # All measurements per height from the wire (devices WS_01_01-h1..h5); the
    # retired s2100-10..15 sensors are gone (ADR 0001). Keeps the height and
    # measurement columns so the view can pivot per selected measurement.
    # ``start``/``end`` (UTC) bound the fetch so a dense day-view never scans the
    # whole wire_sensors table; unbounded only where a view genuinely needs it.
    df = await deps.db.get_wire_sensor_readings(start=start, end=end)

    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df.dropna(subset=["time", "device", "value"])


async def latest_wire_date(wire: str, timezone: str) -> date | None:
    """Most recent local day ``wire`` reported, from the cheap device summary.

    Uses a single GROUP BY aggregate (last-seen per virtual device) rather than
    pulling readings, so the default "latest day with data" never costs a table
    scan. ``None`` when the wire has no readings yet.
    """
    summary = await deps.db.get_wire_device_summary()
    seens = [
        summary[device]["last_seen"]
        for device in (wire_device_id(wire, h) for h in WIRE_SENSOR_HEIGHTS)
        if device in summary and summary[device].get("last_seen") is not None
    ]
    if not seens:
        return None
    ts = pd.Timestamp(max(seens))
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.tz_convert(timezone).date()


def day_window_utc(local_date: date, timezone: str, lookback_hours: float):
    """UTC (start, end) bounds for the local ``local_date`` plus a pre-day look-back.

    ``end`` is the next local midnight (exclusive); ``start`` reaches back
    ``lookback_hours`` before local midnight so trailing-window metrics (fungal
    wet-hours) can accumulate across the prior night.
    """
    day_start = pd.Timestamp(local_date, tz=timezone)
    start = (day_start - pd.Timedelta(hours=lookback_hours)).tz_convert("UTC").to_pydatetime()
    end = (day_start + pd.Timedelta(days=1)).tz_convert("UTC").to_pydatetime()
    return start, end


### Filter to a single day ###
def filter_for_day(
    df, timezone, target_date=None, use_latest_date_in_data=USE_LATEST_DATE_IN_DATA,
):
    """Return the readings for one local day plus that day's start timestamp.

    ``target_date`` (a ``datetime.date``) pins an explicit day — used by the
    ``?date=`` URL param. When it's ``None`` the day defaults to today (or the
    latest day present in the data when ``use_latest_date_in_data`` is set).
    """
    df_local = df.copy()
    df_local["time_local"] = df_local["time"].dt.tz_convert(timezone)

    if target_date is not None:
        target_day = pd.Timestamp(target_date, tz=timezone).normalize()
    elif use_latest_date_in_data:
        target_day = df_local["time_local"].max().normalize()
    else:
        target_day = pd.Timestamp.now(tz=timezone).normalize()

    next_day = target_day + pd.Timedelta(days=1)

    mask = (
        (df_local["time_local"] >= target_day) &
        (df_local["time_local"] < next_day)
    )

    return df_local.loc[mask].drop(columns=["time_local"]), target_day


def series_for(df_day, device, measurement):
    """Time-sorted value list for one height-device + measurement on the day."""
    if df_day.empty:
        return []
    d = df_day[
        (df_day["device"] == device) & (df_day["measurement"] == measurement)
    ].sort_values("time")
    return d["value"].tolist()


### Metrics ###
def compute_sensor_metrics(df_day, measurement, wire):
    """Latest value per height for ``wire``/``measurement`` (+ daily DLI, PAR only).

    ``sensor_id`` is the SVG box id (``height_N``); the wire device it reads is
    derived from the selected wire and height.
    """
    rows = []
    data = df_day[df_day["measurement"] == measurement] if not df_day.empty else df_day

    for height in WIRE_SENSOR_HEIGHTS:
        box_id = f"height_{height}"
        device = wire_device_id(wire, height)
        d = (
            data[data["device"] == device].sort_values("time")
            if not data.empty else data
        )

        if d.empty:
            rows.append({
                "sensor_id": box_id,
                "latest_value": None,
                "dli_today": None,
            })
            continue

        latest = d.iloc[-1]

        rows.append({
            "sensor_id": box_id,
            "latest_value": float(latest["value"]),
            # DLI is a PAR-only aggregate; left empty for other measurements.
            "dli_today": compute_dli(d) if measurement == "par" else None,
        })

    return pd.DataFrame(rows)
