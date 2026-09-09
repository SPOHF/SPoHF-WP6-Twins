"""Season config for the blue twin.

Blue-only config read from the top-level ``seasons`` key in blue's
``metadata.yaml`` (the shared metadata registry ignores it, keeping ``shared/``
twin-agnostic). Mirrors red's ``crop_cycles/config.py``: the models declare no
defaults, so a missing or malformed block fails loudly at load rather than
silently running on guessed dates.

Blue declares seasons but no cohort rhythm, and that is the whole difference
from red. A blueberry bush carries one crop per season, so a season *is* the
period a treatment is measured over; there is no interval producing overlapping
units, and nothing to generate. What red derives from arithmetic, blue reads
straight from config.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from wp6_data.shared.series import PeriodConfig, SeriesMetric

# Blue's names for the shared vocabulary. The weather metric is the seam that
# would let a plot's own sensors replace the farm's weather station later: it is
# a device name in config, not a branch in code.
WeatherMetric = SeriesMetric
SeasonConfig = PeriodConfig


class WeatherConfig(BaseModel):
    metrics: list[WeatherMetric]


class SeasonsConfig(BaseModel):
    weather: WeatherConfig
    seasons: list[SeasonConfig]

    def metric(self, key: str) -> WeatherMetric:
        """The declared weather metric ``key``, or the first as a fallback."""
        for m in self.weather.metrics:
            if m.key == key:
                return m
        return self.weather.metrics[0]


def load_seasons(yaml_path: Path) -> SeasonsConfig:
    """Load and validate the ``seasons`` block from blue's metadata YAML.

    Raises if the file or the key is absent, or if any value is missing — the
    view must never run on implicit dates. Each metric validates its own agg.
    """
    if not yaml_path.exists():
        raise ValueError(f"no metadata file at {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if "seasons" not in raw:
        raise ValueError(f"no 'seasons' block in {yaml_path}")
    return SeasonsConfig(**raw["seasons"])
