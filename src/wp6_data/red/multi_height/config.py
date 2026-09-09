"""Metric vocabulary and cross-wire config for the red multi-height views.

A leaf module by design: it imports only the wire's structural facts, never the
data layer, so ``deps`` can load the config at import time without dragging the
database in behind it (the shape ``risk/config.py`` already has).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from ..db import WIRE_SENSOR_MEASUREMENTS

# The three quantities the crop-climate page derives from the measured ones, and
# the full metric vocabulary a multi-height view speaks. Every metric here is a
# series per growth section per day, so anything that can chart one can chart all.
DERIVED_METRICS = ("dli", "vpd", "fungal")
CROP_METRICS = (*WIRE_SENSOR_MEASUREMENTS, *DERIVED_METRICS)


# The measurements each metric is actually built from. A derived metric is only
# as observed as its parents: Height DLI is PAR integrated, fungal wet-hours are
# humidity accumulated, and VPD needs temperature *and* humidity at the same
# instant. Coverage is counted against these rather than against the device, so
# "this wire reported 15 h" can never be said about a metric it never measured.
METRIC_SOURCES = {
    "par": ("par",),
    "temp": ("temp",),
    "hum": ("hum",),
    "co2": ("co2",),
    "dli": ("par",),
    "vpd": ("temp", "hum"),
    "fungal": ("hum",),
}


class UniformityConfig(BaseModel):
    """What it takes for the declared wires to count as reading the same thing.

    Declares **no defaults**: a missing or malformed ``uniformity`` block fails
    at load rather than silently comparing wires against guessed numbers — the
    rule ``risk/config.py`` and ``crop_cycles/config.py`` already follow.
    """

    min_coverage_hours: float
    # Per metric, the spread at which disagreement is worth reporting. Doubles
    # as the tint's saturation point, so the colour and the verdict can never
    # tell the reader two different stories.
    notable_spread: dict[str, float]


def load_uniformity_config(yaml_path: Path) -> UniformityConfig:
    """Load and validate the ``uniformity`` block from a twin metadata YAML.

    Red-only config, like ``growth_sections`` and ``risk_thresholds``: the
    shared metadata registry ignores the key, keeping ``shared/`` twin-agnostic.
    """
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if "uniformity" not in raw:
        raise ValueError(f"no 'uniformity' block in {yaml_path}")
    config = UniformityConfig(**raw["uniformity"])
    missing = [m for m in CROP_METRICS if m not in config.notable_spread]
    if missing:
        raise ValueError(
            f"uniformity.notable_spread is missing {missing} in {yaml_path}"
        )
    return config
