"""Pure metric functions for the red prescriptive view.

All functions are side-effect-free and operate on tidy pandas frames so they are
unit-testable without a database. Four families:

- **Height DLI** — the day's integral of per-height PAR (moved here from the
  multi-height route so the view and the risk engine share one integral; see
  CONTEXT "Height DLI", distinct from the modelled whole-greenhouse DLI).
- **VPD** — vapour-pressure deficit from temp + humidity at one height (Tetens).
- **Fungal wet-hours** — trailing-window accumulation of time spent above a
  high-RH threshold (the Botrytis-pressure proxy).
- **CO₂ depletion** — daylight-gated ppm below a carbon-limitation floor (PAR
  shows the canopy is lit and therefore drawing CO₂ down).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Gaps longer than this between readings are clipped so a missing stretch can't
# inflate an integral/accumulation (matches the multi-height view's behaviour).
_MAX_GAP_SECONDS = 900


### Height DLI (PAR integral) ###
def _dli_increments(sensor_df: pd.DataFrame) -> pd.DataFrame | None:
    """Per-reading DLI contributions (mol/m²) via trapezoidal integration.

    Returns the frame sorted by time with a ``dli_increment`` column — each
    interval's PAR (averaged across its endpoints) times its duration. Gaps are
    clipped to 15 min. ``None`` when there are too few readings to integrate.
    """
    d = sensor_df.sort_values("time").copy()

    if len(d) < 2:
        return None

    d["next_time"] = d["time"].shift(-1)
    d["next_value"] = d["value"].shift(-1)

    d["dt_seconds"] = (d["next_time"] - d["time"]).dt.total_seconds()
    d["dt_seconds"] = d["dt_seconds"].clip(lower=0, upper=_MAX_GAP_SECONDS)

    d["avg_value"] = (d["value"] + d["next_value"]) / 2
    d = d.dropna(subset=["dt_seconds", "avg_value"])

    d["dli_increment"] = (d["avg_value"] * d["dt_seconds"]) / 1_000_000
    return d


def compute_dli(sensor_df: pd.DataFrame) -> float | None:
    """Total Height DLI (mol/m²) for one height's PAR readings over the day."""
    d = _dli_increments(sensor_df)
    if d is None:
        return None
    return float(d["dli_increment"].sum())


def compute_cumulative_dli(sensor_df: pd.DataFrame) -> pd.DataFrame | None:
    """Running Height DLI (mol/m²): ``time`` + ``cumulative_dli`` columns.

    The DLI accrued from the start of the data up to each timestamp. ``None``
    when there are too few readings.
    """
    d = _dli_increments(sensor_df)
    if d is None:
        return None
    d["cumulative_dli"] = d["dli_increment"].cumsum()
    return d[["time", "cumulative_dli"]]


### VPD (vapour pressure deficit) ###
def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    """Saturation vapour pressure (kPa) at ``temp_c`` via the Tetens equation."""
    return 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))


def vpd_kpa(temp_c: float, rh_pct: float) -> float:
    """Vapour pressure deficit (kPa) from temperature (°C) and RH (%)."""
    return float(saturation_vapor_pressure_kpa(temp_c) * (1.0 - rh_pct / 100.0))


def vpd_series(height_df: pd.DataFrame) -> pd.DataFrame:
    """VPD over time for one height, from its temp + hum readings.

    ``height_df`` is tidy long (columns ``time``, ``measurement``, ``value``)
    for a single height. Temp and hum are aligned on shared timestamps; rows
    missing either are dropped. Returns ``time`` + ``value`` (kPa), time-sorted.
    Empty when temp or hum is absent.
    """
    empty = pd.DataFrame(columns=["time", "value"])
    if height_df.empty:
        return empty

    wide = height_df.pivot_table(
        index="time", columns="measurement", values="value", aggfunc="last",
    )
    if "temp" not in wide.columns or "hum" not in wide.columns:
        return empty

    wide = wide.dropna(subset=["temp", "hum"]).sort_index()
    if wide.empty:
        return empty

    svp = 0.6108 * np.exp((17.27 * wide["temp"]) / (wide["temp"] + 237.3))
    vpd = svp * (1.0 - wide["hum"] / 100.0)
    return pd.DataFrame({"time": wide.index, "value": vpd.to_numpy()})


### CO₂ depletion (daylight carbon-limitation) ###
def co2_depletion_series(
    height_df: pd.DataFrame, floor_ppm: float, daylight_par: float,
) -> pd.DataFrame:
    """Daylight CO₂-depletion severity over time for one height.

    ``height_df`` is tidy long (columns ``time``, ``measurement``, ``value``)
    for a single height. CO₂ and PAR are aligned on shared timestamps; a row is
    only considered when PAR exceeds ``daylight_par`` (the canopy is lit by sun
    or lamps, so it is photosynthesising and actually drawing CO₂ down). The
    value is ``floor_ppm - co2`` clipped at 0 — i.e. how many ppm the level sits
    below the floor while lit; 0 when above the floor or in the dark. Returns
    ``time`` + ``value`` (ppm below floor), time-sorted. Empty when CO₂ or PAR is
    absent, or no reading falls in daylight.
    """
    empty = pd.DataFrame(columns=["time", "value"])
    if height_df.empty:
        return empty

    wide = height_df.pivot_table(
        index="time", columns="measurement", values="value", aggfunc="last",
    )
    if "co2" not in wide.columns or "par" not in wide.columns:
        return empty

    lit = wide.dropna(subset=["co2", "par"]).sort_index()
    lit = lit[lit["par"] > daylight_par]
    if lit.empty:
        return empty

    severity = np.clip(floor_ppm - lit["co2"], 0, None)
    return pd.DataFrame({"time": lit.index, "value": severity.to_numpy()})


### Fungal wet-hours ###
def wet_hours_series(
    hum_df: pd.DataFrame,
    rh_pct: float,
    window_hours: float,
    max_gap_seconds: float = _MAX_GAP_SECONDS,
) -> pd.DataFrame:
    """Trailing-window wet-hours for one height's humidity series.

    For each reading, the time until the next reading (clipped to
    ``max_gap_seconds``) counts as "wet" when RH exceeds ``rh_pct``. The value at
    each timestamp is the sum of wet time over the trailing ``window_hours``,
    expressed in hours. Returns ``time`` + ``value``, time-sorted; empty in,
    empty out.
    """
    if hum_df.empty:
        return pd.DataFrame(columns=["time", "value"])

    d = hum_df.sort_values("time").copy()
    dt = (d["time"].shift(-1) - d["time"]).dt.total_seconds()
    dt = dt.clip(lower=0, upper=max_gap_seconds).fillna(0.0)
    d["wet_s"] = np.where(d["value"] > rh_pct, dt, 0.0)

    rolled = (
        d.set_index("time")["wet_s"]
        .rolling(pd.Timedelta(hours=window_hours))
        .sum()
    )
    return pd.DataFrame({"time": rolled.index, "value": rolled.to_numpy() / 3600.0})
