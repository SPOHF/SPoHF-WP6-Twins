"""The multi-height wires as one vertical cross-section of the house, step by step.

The page's microclimate mode colours a slice that runs along the row of wires
and up through the canopy. This module only lays the measurements out on that
slice: per metric, per step of the page's timeline, a value for every
(wire, height), in the configured order along the row. It interpolates nothing.
The browser fills the space between the points for drawing, and the measured
points stay the only numbers the page states.

Pure: it reads the tidy wire-readings frame and the configuration, nothing else.
"""

from __future__ import annotations

from datetime import date

import pandas as pd  # type: ignore[import-untyped]

from wp6_data.red.db import wire_device_id
from wp6_data.red.greenhouse import state as S
from wp6_data.red.greenhouse.config import Microclimate
from wp6_data.red.multi_height.cells import METRIC_LABELS
from wp6_data.red.multi_height.data import filter_for_day
from wp6_data.red.risk.metrics import vpd_series
from wp6_data.shared.i18n import t


def _on_grid(points: pd.DataFrame, grid: pd.DatetimeIndex, tz: str) -> list[float | None]:
    """Mean per step of ``points`` (``time``, ``value``), one entry per grid step.

    Steps are labelled by their start, as the page's LetsGrow steps are, so the
    two line up by local clock time. A step with no reading stays ``None``.
    """
    if points.empty:
        return [None] * len(grid)
    series = (
        points.assign(time=pd.to_datetime(points["time"]).dt.tz_convert(tz))
        .set_index("time")["value"]
        .astype(float)
        .resample(S.STEP)
        .mean()
        .reindex(grid)
    )
    return [None if pd.isna(v) else round(float(v), 2) for v in series]


def _height_series(hdf: pd.DataFrame, metric: str) -> pd.DataFrame:
    """One height's readings of ``metric`` as ``time`` + ``value``.

    VPD is formed per reading, from temperature and humidity at the same
    instant, before any averaging: the mean of VPDs is not the VPD of means.
    """
    if metric == "vpd":
        return vpd_series(hdf)
    return hdf.loc[hdf["measurement"] == metric, ["time", "value"]]


def _scale(step: list[list[float | None]], min_span: float) -> list[float] | None:
    """One step's colour range: its lowest to highest reading, never narrower
    than ``min_span``.

    Per step, because the section is about *where* the air differs at that
    moment; a day-wide range would spend the colours on night against noon.
    The floor keeps sensors that agree within the spread the twin counts as
    notable from being painted as opposites.
    """
    flat = [v for wire in step for v in wire if v is not None]
    if not flat:
        return None
    lo, hi = min(flat), max(flat)
    if hi - lo < min_span:
        mid = (lo + hi) / 2
        lo, hi = mid - min_span / 2, mid + min_span / 2
    return [round(lo, 2), round(hi, 2)]


def build_microclimate_day(
    df: pd.DataFrame,
    mc: Microclimate,
    installed: list[str],
    day: date,
    tz: str,
    min_span: dict[str, float],
) -> dict:
    """The cross-section for one local day.

    ``df`` is the tidy wire-readings frame (``device``, ``measurement``,
    ``time``, ``value``) covering at least the day; ``installed`` the wires
    upstream's map lists; ``min_span`` per metric the narrowest colour range.

    ``metrics[m]["values"][step][wire][height]`` follows ``steps``, the
    configured wire order and ``heights`` (H1 at the top first);
    ``metrics[m]["scales"][step]`` is that step's colour range.
    """
    df_day, day_start = filter_for_day(df, tz, target_date=day)
    grid = pd.date_range(day_start, day_start + pd.Timedelta(days=1), freq=S.STEP, inclusive="left")
    heights = sorted(mc.heights_m)

    # per metric, per wire, per height: the day's series on the grid
    series: dict[str, list[list[list[float | None]]]] = {m: [] for m in mc.metrics}
    for wire in mc.wires:
        on_wire = {m: [] for m in mc.metrics}
        for height in heights:
            hdf = df_day[df_day["device"] == wire_device_id(wire.id, height)]
            for m in mc.metrics:
                on_wire[m].append(_on_grid(_height_series(hdf, m), grid, tz))
        for m in mc.metrics:
            series[m].append(on_wire[m])

    cells = len(grid) * len(heights)
    metrics = {}
    for m, by_wire in series.items():
        # the same numbers turned step-first, as the page walks the timeline
        values = [[[col[si] for col in wire] for wire in by_wire] for si in range(len(grid))]
        metrics[m] = {
            "unit": METRIC_LABELS[m][1],
            "scales": [_scale(step, min_span[m]) for step in values],
            "values": values,
            # per wire: the share of (step, height) cells with a reading
            "coverage": [
                round(sum(v is not None for col in wire for v in col) / cells, 3)
                for wire in by_wire
            ],
        }

    configured = [w.id for w in mc.wires]
    notes = [
        t("greenhouse.note.wire_not_installed", wire=w) for w in configured if w not in installed
    ]
    unplaced = [w for w in installed if w not in configured]
    if unplaced:
        notes.append(t("greenhouse.note.wire_not_placed", wires=", ".join(unplaced)))
    if not any(any(metrics[m]["coverage"]) for m in metrics):
        notes.append(t("greenhouse.note.no_wire_data"))

    return {
        "date": day.isoformat(),
        "tz": tz,
        "runs": mc.runs,
        "steps": [s.strftime("%H:%M") for s in grid],
        "wires": [{"id": w.id, "at_m": w.at_m, "installed": w.id in installed} for w in mc.wires],
        "heights": [{"h": h, "m": mc.heights_m[h]} for h in heights],
        "metrics": metrics,
        "notes": notes,
    }

