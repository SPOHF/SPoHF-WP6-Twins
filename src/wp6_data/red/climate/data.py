"""Data-access seam for red's climate model.

The single place (outside the composition root) where the climate model touches
``wp6_data.red.deps.db``, mirroring ``red/dli/data.py`` so red's direct-MySQL
surface stays narrow.

Which MySQL table a device lives in is **not** hardcoded here: it comes from the
device's ``type`` in ``metadata.yaml``, which is already the platform's source of
truth for device enumeration (red ADR 0001). Adding a sensor to the model is a
metadata and config edit, not a code edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.red import deps
from wp6_data.red.multi_height.data import load_wire_readings

if TYPE_CHECKING:
    from datetime import datetime

    from wp6_data.red.db import MySQLConnection

# Eleven months of 5-minute readings is ~95k rows per device; the cap is a
# runaway guard, not a window. ``get_readings`` orders newest-first, so a cap
# that bites would silently truncate the *oldest* data — exactly the seasonal
# coverage the model needs — hence the generous headroom.
READING_LIMIT = 1_000_000


def is_connected() -> bool:
    """Whether the live MySQL feed is available (the routes' guard pattern)."""
    return deps.db is not None


def require_db() -> MySQLConnection:
    """The live MySQL connection, raising when the app started without one."""
    if deps.db is None:
        raise RuntimeError("Database not connected")
    return deps.db


def table_for(device: str) -> str:
    """The MySQL table a device reports into, from its metadata ``type``."""
    meta = deps.metadata.devices.get(device)
    if meta is None or not meta.type:
        raise KeyError(f"device {device!r} is not declared in metadata")
    return meta.type


async def sensor_series(
    device: str,
    sensor: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """One device/sensor pair as ``time, value``, sorted.

    Returns a typed empty frame when the device reported nothing in the window,
    so a caller can distinguish "no data" from "not asked for" without guarding
    on column presence.
    """
    df = await require_db().get_readings(
        table=table_for(device), device_id=device,
        start=start, end=end, limit=READING_LIMIT,
    )
    if df.empty:
        return pd.DataFrame({"time": pd.Series(dtype="datetime64[ns, UTC]"),
                             "value": pd.Series(dtype=float)})
    picked = df[df["sensor"] == sensor][["time", "value"]]
    return picked.sort_values("time").reset_index(drop=True)


async def sensor_frames(
    wanted: dict[str, tuple[str, str]],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """Several named ``(device, sensor)`` pairs at once.

    ``wanted`` maps the name the model uses to the pair it comes from, e.g.
    ``{"temp": ("s2103-01-temp-hum-co2", "temp")}``. Series that come back empty
    are dropped rather than carried as empty columns — an absent input must not
    become a column of NaN that silently removes every row downstream.
    """
    frames: dict[str, pd.DataFrame] = {}
    for name, (device, sensor) in wanted.items():
        series = await sensor_series(device, sensor, start, end)
        if not series.empty:
            frames[name] = series
    return frames


async def wire_frames(
    wire: str,
    measurement: str,
    heights: list[int],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """One wire's readings for ``measurement``, keyed ``h1``..``h5``.

    Reuses ``multi_height.data.load_wire_readings`` rather than issuing its own
    query, so the wide-table unpivot and the null handling stay in one place.
    Only the ``heights`` asked for are returned; the caller gets them from
    config, because each wire is broken differently and none may be assumed to
    report everything.
    """
    from wp6_data.red.db import wire_physical_id

    df = await load_wire_readings(start=start, end=end)
    if df.empty:
        return {}

    scoped = df[
        (df["device"].map(wire_physical_id) == wire)
        & (df["measurement"] == measurement)
        & (df["height"].isin(heights))
    ]
    return {
        f"h{height}": group[["time", "value"]].sort_values("time").reset_index(drop=True)
        for height, group in scoped.groupby("height")
    }
