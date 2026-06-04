"""Risk thresholds for the red prescriptive view.

Red-only config read from the top-level ``risk_thresholds`` key in red's
``metadata.yaml`` (the shared metadata registry ignores it, keeping ``shared/``
twin-agnostic). The values are PROVISIONAL — the CLI/engine exist to validate
them against real data — so they live in config, never as code constants.

Models declare **no defaults**: a missing or malformed ``risk_thresholds`` block
fails loudly at load rather than silently falling back to guessed numbers.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class FungalThresholds(BaseModel):
    rh_pct: float          # RH above which an interval counts as "wet"
    window_hours: float    # trailing window for wet-hours accumulation
    active_wet_hours: float  # wet-hours above which a fungal episode is active


class VpdBand(BaseModel):
    band_min_kpa: float
    band_max_kpa: float


class CanopyDli(BaseModel):
    target_mol: float      # canopy (H1) DLI target, mol/m²/day


class Co2Floor(BaseModel):
    # CO₂ depletion is daylight-only: the crop draws CO₂ down while
    # photosynthesising, so a low level matters only when PAR shows the canopy
    # is lit (sun or lamps). Below the floor with the lights on = carbon-limited.
    floor_ppm: float       # daytime CO₂ below this = carbon-limited (≈ambient)
    daylight_par: float    # PAR above which the floor applies (photoperiod gate)


class EpisodeConfig(BaseModel):
    min_duration_minutes: float


class RiskThresholds(BaseModel):
    """The full red risk-threshold set (stamped onto each emitted episode)."""

    fungal: FungalThresholds
    vpd: VpdBand
    canopy_dli: CanopyDli
    co2: Co2Floor
    episode: EpisodeConfig


def load_risk_thresholds(yaml_path: Path) -> RiskThresholds:
    """Load and validate the ``risk_thresholds`` block from a twin metadata YAML.

    Raises if the file or the ``risk_thresholds`` key is absent, or if any value
    is missing — the engine must never run on implicit defaults.
    """
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    if "risk_thresholds" not in raw:
        raise ValueError(f"no 'risk_thresholds' block in {yaml_path}")
    return RiskThresholds(**raw["risk_thresholds"])
