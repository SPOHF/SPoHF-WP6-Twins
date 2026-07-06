"""Day view-model for the red "Crop Climate by Height" page.

Splits the page into a pure computation and a thin persistence read:

- :func:`build_crop_climate_day` computes each growth section's live series for
  the shown day from the readings frame alone — the measured series per
  measurement type, plus the derived Height DLI, VPD and fungal wet-hours via
  the shared risk metrics — and the per-column bounds that drive the relative
  cell tint. No I/O, so it is unit-testable without a database.
- :func:`assemble_crop_climate_day` adds the persisted per-section risk state.
  Status badges deliberately reflect that state "as of the last Update/Rebuild"
  while the cells are computed live from the day's readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from psycopg_pool import AsyncConnectionPool

from ..db import WIRE_SENSOR_MEASUREMENTS, wire_device_id
from ..growth_sections import GrowthSection
from ..risk import store
from ..risk.config import RiskThresholds
from ..risk.metrics import compute_cumulative_dli, vpd_series, wet_hours_series
from .data import filter_for_day, series_for


@dataclass(frozen=True)
class SectionView:
    """One growth section's live series for the shown day."""

    height: int
    label: str
    series: dict[str, list[float]]  # measured, keyed by measurement type
    height_dli: list[float]         # cumulative Height DLI (mol/m²)
    vpd: list[float]                # kPa
    fungal: list[float]             # trailing wet-hours, trimmed to the day


@dataclass(frozen=True)
class CropClimateDay:
    """Everything the crop-climate table renders for one wire + day."""

    day_start: pd.Timestamp  # tz-aware local midnight of the shown day
    sections: list[SectionView]
    # Per-column (latest across the heights) bounds for the relative cell tint.
    bounds: dict[str, tuple[float, float]]
    # Persisted per-section risk state ("as of last build") driving the badges.
    state_by_height: dict[int, dict[str, Any]] = field(default_factory=dict)
    as_of: datetime | None = None


def build_crop_climate_day(
    df: pd.DataFrame,
    wire: str,
    sections: list[GrowthSection],
    thresholds: RiskThresholds,
    timezone: str,
    target_date: date | None = None,
) -> CropClimateDay:
    """Pure per-section live series + bounds for one day (no persisted state).

    ``df`` is the tidy readings frame for the day *plus* the fungal look-back
    window, so wet-hours can accumulate across the prior night; every other
    series is scoped to the shown day. Derived series come from the shared risk
    metrics, computed once per section.
    """
    df_day, day_start = filter_for_day(df, timezone, target_date=target_date)

    section_views = []
    for section in sections:
        device = wire_device_id(wire, section.height)
        measured = {
            m: series_for(df_day, device, m) for m in WIRE_SENSOR_MEASUREMENTS
        }

        hdf = df_day[df_day["device"] == device]
        par_df = hdf[hdf["measurement"] == "par"][["time", "value"]]
        cum = compute_cumulative_dli(par_df)
        height_dli = [] if cum is None or cum.empty else cum["cumulative_dli"].tolist()

        v = vpd_series(hdf)
        vpd = [] if v.empty else v["value"].tolist()

        # Fungal wet-hours read the full window (day + look-back) so the trailing
        # window accumulates across the prior night; the shown series trims to
        # the day.
        hum_window = df[(df["device"] == device) & (df["measurement"] == "hum")][
            ["time", "value"]
        ]
        w = wet_hours_series(
            hum_window, thresholds.fungal.rh_pct, thresholds.fungal.window_hours,
        )
        if not w.empty:
            w = w[w["time"] >= day_start]
        fungal = [] if w.empty else w["value"].tolist()

        section_views.append(SectionView(
            height=section.height,
            label=section.label,
            series=measured,
            height_dli=height_dli,
            vpd=vpd,
            fungal=fungal,
        ))

    bounds = {}
    for m in WIRE_SENSOR_MEASUREMENTS:
        latests = [sv.series[m][-1] for sv in section_views if sv.series[m]]
        bounds[m] = (min(latests), max(latests)) if latests else (0.0, 1.0)

    return CropClimateDay(day_start=day_start, sections=section_views, bounds=bounds)


async def assemble_crop_climate_day(
    pool: AsyncConnectionPool,
    df: pd.DataFrame,
    wire: str,
    sections: list[GrowthSection],
    thresholds: RiskThresholds,
    timezone: str,
    target_date: date | None = None,
) -> CropClimateDay:
    """The live day view-model plus the wire's persisted per-section risk state.

    The state drives the badges "as of the last Update/Rebuild" — it is read
    as-is, never recomputed here.
    """
    day = build_crop_climate_day(
        df, wire, sections, thresholds, timezone, target_date=target_date,
    )
    state_by_height = {r["height"]: r for r in await store.read_state(pool, wire)}
    as_of = max((r["built_at"] for r in state_by_height.values()), default=None)
    return replace(day, state_by_height=state_by_height, as_of=as_of)
