"""Risk engine: tidy wire readings -> per-section state + risk episodes.

Pure and side-effect-free (``evaluate`` does no I/O), so it runs identically from
the CLI, a test, or a future background writer. Four risks per growth section:

- **VPD** out-of-band — a time-series episode (severity = distance outside band).
- **Fungal wet-hours** above the active level — a time-series episode.
- **CO₂ depletion** — a time-series episode, but daylight-gated: a low level
  matters only while PAR shows the canopy is lit and drawing CO₂ down.
- **Canopy light deficit** — H1 only, a *daily* episode (the day's Height DLI
  below target); a daily integral has no sub-daily "active" moment.

Each episode is stamped with the threshold values that produced it, so an audit
never conflates threshold eras (ADR 0002).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ..growth_sections import GrowthSection
from .config import RiskThresholds
from .episodes import Episode, detect_episodes
from .metrics import co2_depletion_series, compute_dli, vpd_series, wet_hours_series


@dataclass
class SectionState:
    """Latest-known risk state for one growth section."""

    height: int
    label: str
    height_dli: float | None
    vpd_latest: float | None
    vpd_in_band: bool | None
    wet_hours_latest: float | None
    fungal_active: bool | None
    co2_latest: float | None
    co2_depleted: bool | None  # daylight CO₂ below floor; None when never lit
    canopy_deficit: bool | None  # H1 only; None for the other sections


@dataclass
class RiskEpisodeRecord:
    """An episode tagged with its section, risk and the thresholds used."""

    height: int
    label: str
    risk: str  # "vpd" | "fungal" | "co2" | "canopy"
    start: datetime
    end: datetime | None
    peak: float
    thresholds: dict[str, Any]


@dataclass
class RiskEvaluation:
    states: list[SectionState] = field(default_factory=list)
    episodes: list[RiskEpisodeRecord] = field(default_factory=list)


def _record(section: GrowthSection, risk: str, ep: Episode, snap: dict) -> RiskEpisodeRecord:
    return RiskEpisodeRecord(
        height=section.height, label=section.label, risk=risk,
        start=ep.start, end=ep.end, peak=ep.peak, thresholds=snap,
    )


def _fungal_snapshot(t: RiskThresholds) -> dict[str, Any]:
    return {
        "rh_pct": t.fungal.rh_pct,
        "window_hours": t.fungal.window_hours,
        "active_wet_hours": t.fungal.active_wet_hours,
        "min_duration_minutes": t.episode.min_duration_minutes,
    }


def _vpd_snapshot(t: RiskThresholds) -> dict[str, Any]:
    return {
        "band_min_kpa": t.vpd.band_min_kpa,
        "band_max_kpa": t.vpd.band_max_kpa,
        "min_duration_minutes": t.episode.min_duration_minutes,
    }


def _co2_snapshot(t: RiskThresholds) -> dict[str, Any]:
    return {
        "floor_ppm": t.co2.floor_ppm,
        "daylight_par": t.co2.daylight_par,
        "min_duration_minutes": t.episode.min_duration_minutes,
    }


def _canopy_snapshot(t: RiskThresholds) -> dict[str, Any]:
    return {"target_mol": t.canopy_dli.target_mol}


def _latest_day_dli(height_df: pd.DataFrame, tz: str) -> float | None:
    """Height DLI for the most recent local day present in this height's PAR.

    Days are bucketed in ``tz`` (the display timezone) so the verdict matches the
    local day the UI shows, not a UTC calendar day that can straddle midnight.
    """
    if height_df.empty:
        return None
    par = height_df[height_df["measurement"] == "par"][["time", "value"]]
    if par.empty:
        return None
    local_date = par["time"].dt.tz_convert(tz).dt.date
    last_day = local_date.max()
    return compute_dli(par[local_date == last_day])


def _vpd_episodes(height_df, section, t, min_dur) -> list[RiskEpisodeRecord]:
    v = vpd_series(height_df)
    if v.empty:
        return []
    vals = v["value"].to_numpy()
    severity = np.clip(
        np.maximum(t.vpd.band_min_kpa - vals, vals - t.vpd.band_max_kpa), 0, None
    )
    frame = pd.DataFrame(
        {"time": v["time"].to_numpy(), "value": severity, "active": severity > 0}
    )
    return [
        _record(section, "vpd", ep, _vpd_snapshot(t))
        for ep in detect_episodes(frame, min_dur)
    ]


def _fungal_episodes(height_df, section, t, min_dur) -> list[RiskEpisodeRecord]:
    hum = height_df[height_df["measurement"] == "hum"][["time", "value"]]
    w = wet_hours_series(hum, t.fungal.rh_pct, t.fungal.window_hours)
    if w.empty:
        return []
    active = w["value"].to_numpy() > t.fungal.active_wet_hours
    frame = pd.DataFrame(
        {"time": w["time"].to_numpy(), "value": w["value"].to_numpy(), "active": active}
    )
    return [
        _record(section, "fungal", ep, _fungal_snapshot(t))
        for ep in detect_episodes(frame, min_dur)
    ]


def _co2_episodes(height_df, section, t, min_dur) -> list[RiskEpisodeRecord]:
    c = co2_depletion_series(height_df, t.co2.floor_ppm, t.co2.daylight_par)
    if c.empty:
        return []
    vals = c["value"].to_numpy()
    frame = pd.DataFrame(
        {"time": c["time"].to_numpy(), "value": vals, "active": vals > 0}
    )
    return [
        _record(section, "co2", ep, _co2_snapshot(t))
        for ep in detect_episodes(frame, min_dur)
    ]


def _canopy_episodes(height_df, section, t, tz) -> list[RiskEpisodeRecord]:
    """One daily episode per local day the canopy (H1) Height DLI is below target.

    Days are bucketed in ``tz`` (and stamped at local midnight) so the daily
    integral lines up with the local day the UI presents, not a UTC day.
    """
    if height_df.empty:
        return []
    par = height_df[height_df["measurement"] == "par"][["time", "value"]].copy()
    if par.empty:
        return []
    par["date"] = par["time"].dt.tz_convert(tz).dt.date
    days = sorted(par["date"].unique())
    out: list[RiskEpisodeRecord] = []
    for i, day in enumerate(days):
        dli = compute_dli(par[par["date"] == day][["time", "value"]])
        if dli is None or dli >= t.canopy_dli.target_mol:
            continue
        start = pd.Timestamp(day, tz=tz)
        end = None if i == len(days) - 1 else start + pd.Timedelta(days=1)
        ep = Episode(start=start, end=end, peak=float(t.canopy_dli.target_mol - dli))
        out.append(_record(section, "canopy", ep, _canopy_snapshot(t)))
    return out


def evaluate(
    df: pd.DataFrame,
    sections: list[GrowthSection],
    thresholds: RiskThresholds,
    tz: str = "UTC",
) -> RiskEvaluation:
    """Evaluate all risks for every growth section over ``df`` (one wire's readings).

    ``df`` is tidy long with columns ``height``, ``measurement``, ``time``,
    ``value`` (as returned by ``get_wire_sensor_readings``, scoped to one wire).
    Returns the latest-known state per section plus every risk episode in the
    window. ``tz`` is the timezone the *daily* metrics (Height DLI, canopy
    deficit) are bucketed in, so they align with the local day the UI shows;
    it defaults to UTC for callers that don't care.
    """
    result = RiskEvaluation()
    if not sections:
        return result

    min_dur = timedelta(minutes=thresholds.episode.min_duration_minutes)
    canopy = sections[0]  # sections are ordered top->root; H1 is the canopy

    for section in sections:
        hdf = df[df["height"] == section.height] if not df.empty else df

        result.episodes.extend(_vpd_episodes(hdf, section, thresholds, min_dur))
        result.episodes.extend(_fungal_episodes(hdf, section, thresholds, min_dur))
        result.episodes.extend(_co2_episodes(hdf, section, thresholds, min_dur))

        v = vpd_series(hdf)
        vpd_latest = float(v["value"].iloc[-1]) if not v.empty else None
        in_band = (
            thresholds.vpd.band_min_kpa <= vpd_latest <= thresholds.vpd.band_max_kpa
            if vpd_latest is not None else None
        )

        hum = hdf[hdf["measurement"] == "hum"][["time", "value"]]
        w = wet_hours_series(hum, thresholds.fungal.rh_pct, thresholds.fungal.window_hours)
        wet_latest = float(w["value"].iloc[-1]) if not w.empty else None
        fungal_active = (
            wet_latest > thresholds.fungal.active_wet_hours
            if wet_latest is not None else None
        )

        co2 = hdf[hdf["measurement"] == "co2"][["time", "value"]].sort_values("time")
        co2_latest = float(co2["value"].iloc[-1]) if not co2.empty else None
        c = co2_depletion_series(hdf, thresholds.co2.floor_ppm, thresholds.co2.daylight_par)
        co2_depleted = bool(c["value"].iloc[-1] > 0) if not c.empty else None

        hdli = _latest_day_dli(hdf, tz)
        canopy_deficit = None
        if section.height == canopy.height:
            canopy_deficit = hdli is not None and hdli < thresholds.canopy_dli.target_mol
            result.episodes.extend(_canopy_episodes(hdf, section, thresholds, tz))

        result.states.append(SectionState(
            height=section.height, label=section.label, height_dli=hdli,
            vpd_latest=vpd_latest, vpd_in_band=in_band,
            wet_hours_latest=wet_latest, fungal_active=fungal_active,
            co2_latest=co2_latest, co2_depleted=co2_depleted,
            canopy_deficit=canopy_deficit,
        ))

    return result
