"""Replay frames for the side section: a window of history as a series of snapshots.

Pure (no I/O), like :mod:`.side_section`: the route fetches one window of
readings and hands it in. A *frame* is every wire's last reading at or before
one instant. Readings older than the staleness threshold are kept but flagged,
so the view greys them out instead of silently carrying an old value forward.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd  # type: ignore[import-untyped]

from ..db import WIRE_SENSOR_HEIGHTS
from .side_section import (
    MeasurementStyle,
    NodeReading,
    PlacedNode,
    _wire_of,
    colour_range,
)

MAX_FRAMES = 96
MAX_WINDOW = timedelta(days=14)
MIN_STALE_AFTER = timedelta(hours=1)
STEPS = [
    timedelta(minutes=m) for m in (15, 30, 60, 120, 180, 360, 720, 1440)
]


@dataclass(frozen=True)
class Frame:
    time: pd.Timestamp
    readings: dict[str, dict[int, NodeReading]]


def resolve_window(
    start: datetime | None, end: datetime | None, latest: datetime | None,
) -> tuple[datetime, datetime] | None:
    """Validated ``(start, end)`` of the replay, or ``None`` to show the latest reading.

    ``end`` defaults to the latest available reading. An inverted or empty
    window is rejected; one longer than ``MAX_WINDOW`` keeps its end and has its
    start pulled in, so the page can never be asked for an unbounded replay.
    """
    end = end or latest
    if start is None or end is None or start >= end:
        return None
    return max(start, end - MAX_WINDOW), end


def choose_step(span: timedelta) -> timedelta:
    """Smallest standard step that keeps the window within ``MAX_FRAMES``."""
    for step in STEPS:
        if span / step + 1 <= MAX_FRAMES:
            return step
    return STEPS[-1]


def stale_after(step: timedelta) -> timedelta:
    """A reading is stale once it is older than two steps (and at least an hour)."""
    return max(MIN_STALE_AFTER, 2 * step)


def frame_times(start: datetime, end: datetime, step: timedelta) -> list[pd.Timestamp]:
    """``start``, ``start + step``, ... and always ``end`` as the last frame."""
    times = list(pd.date_range(start, end, freq=step))
    if not times or times[-1] < pd.Timestamp(end):
        times.append(pd.Timestamp(end))
    return times


def build_frames(
    df: pd.DataFrame,
    wires: list[str],
    measurement: str,
    times: list[pd.Timestamp],
    stale: timedelta,
) -> list[Frame]:
    """One frame per instant, from a single pass over the window's readings.

    Per (wire, height) the readings are sorted once and each instant is a binary
    search, so the cost is not frames x rows. A (wire, height) with nothing at or
    before an instant is absent from that frame, never zero-filled.
    """
    out: list[dict[str, dict[int, NodeReading]]] = [{w: {} for w in wires} for _ in times]
    if not df.empty:
        scoped = df[df["measurement"] == measurement].dropna(subset=["value"])
        instants = pd.DatetimeIndex(times)
        if instants.tz is None:
            instants = instants.tz_localize("UTC")
        for (device, height), group in scoped.groupby(["device", "height"]):
            wire = _wire_of(device)
            if wire not in out[0] or int(height) not in WIRE_SENSOR_HEIGHTS:
                continue
            group = group.sort_values("time", kind="stable")
            seen = pd.DatetimeIndex(group["time"])
            values = group["value"].to_numpy()
            at = seen.searchsorted(instants, side="right") - 1
            for i, k in enumerate(at):
                if k < 0:
                    continue
                age = instants[i] - seen[k]
                out[i][wire][int(height)] = NodeReading(
                    float(values[k]), seen[k], stale=age > stale,
                )
    return [Frame(t, r) for t, r in zip(times, out, strict=True)]


def shared_scale(
    frames: list[list[PlacedNode]], style: MeasurementStyle,
) -> tuple[float, float] | None:
    """One colour range over every frame, so a colour change is the greenhouse changing."""
    return colour_range([n for nodes in frames for n in nodes], style)


def frame_index_at(times: list[pd.Timestamp], at: datetime | None) -> int:
    """Index of the frame nearest ``at``; the first frame when ``at`` is absent."""
    if at is None:
        return 0
    target = pd.Timestamp(at)
    return min(range(len(times)), key=lambda i: abs(times[i] - target))
