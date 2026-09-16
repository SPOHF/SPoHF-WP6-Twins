"""Configuration for red's climate model.

Red-only config read from the top-level ``climate_model`` key in red's
``metadata.yaml`` (the shared metadata registry ignores it, keeping ``shared/``
twin-agnostic). Like ``risk/config.py``, the models declare **no defaults**: a
missing or malformed block fails loudly at load rather than training on guessed
dates and sensor ids.

Three things live here rather than in code because they are findings about the
greenhouse, not decisions about the software, and they will change without any
code changing:

- ``training_start`` — supersedes the former ``DEFAULT_TRAINING_START`` constant.
- ``exclusions`` — dated spans no fit may see. The dates are measured; the
  *cause* is recorded as prose and may be corrected independently.
- ``wire_availability`` — which heights each wire actually reports per
  measurement. Each wire is broken differently, so nothing may assume a wire
  reports everything.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]
import yaml
from pydantic import BaseModel, ConfigDict, Field


class OutdoorReference(BaseModel):
    """The local outdoor weather station link 1 calibrates the API against."""

    device: str
    sensors: list[str]


class GreenhouseReference(BaseModel):
    """A candidate greenhouse-level reference for per-height deviations.

    Several are declared and fitted against each other; which one gives the
    tighter deviations is reported rather than assumed.
    """

    key: str
    device: str
    sensors: dict[str, str]  # target name -> sensor tag on the device


class SensorRef(BaseModel):
    """One ``(device, sensor)`` pair."""

    device: str
    sensor: str


class ParReferences(BaseModel):
    """The two PAR references light needs.

    ``natural`` is the above-lamp sensor — the part of canopy light weather can
    explain, and what link 2 predicts. ``canopy`` is the under-lamp sensor, the
    reference link 3 measures per-height deviations against because the wire PAR
    sensors hang under the lamps too. Keeping both named separately is what
    stopped the chain predicting an operator's lamp schedule from the weather.
    """

    natural: SensorRef
    canopy: SensorRef


class Exclusion(BaseModel):
    """A dated span no fit may train on. ``end`` is exclusive."""

    start: date
    end: date
    reason: str

    def covers(self, day: date) -> bool:
        return self.start <= day < self.end


class WireAvailability(BaseModel):
    """Which heights one wire actually reports, per measurement."""

    model_config = ConfigDict(populate_by_name=True)

    available_from: date = Field(alias="from")
    temp: list[int]
    hum: list[int]
    co2: list[int]
    par: list[int]

    def heights(self, measurement: str) -> list[int]:
        """Heights this wire reports for ``measurement``; empty if none."""
        return list(getattr(self, measurement, []) or [])


class ClimateModelConfig(BaseModel):
    """The full climate-model configuration block."""

    training_start: date
    outdoor: OutdoorReference
    references: list[GreenhouseReference]
    par: ParReferences
    horizons_hours: list[int]
    lag_hours: list[int]
    par_floor: float
    exclusions: list[Exclusion]
    wire_availability: dict[str, WireAvailability]

    def reference(self, key: str) -> GreenhouseReference:
        """The declared reference named ``key``; raises if it isn't declared."""
        for candidate in self.references:
            if candidate.key == key:
                return candidate
        declared = ", ".join(r.key for r in self.references)
        raise KeyError(f"no reference {key!r}; declared: {declared}")

    def is_excluded(self, day: date) -> bool:
        """Whether ``day`` falls inside any excluded span."""
        return any(e.covers(day) for e in self.exclusions)

    def drop_excluded(self, df: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
        """Rows of ``df`` outside every excluded span.

        Dropped rather than masked: an excluded stretch is not low-quality data
        to be down-weighted, it is a period the sensors were not measuring what
        their names say.
        """
        if df.empty or not self.exclusions:
            return df
        days = pd.to_datetime(df[time_col], utc=True).dt.date
        keep = ~days.map(self.is_excluded).astype(bool)
        return df[keep]

    def wires_reporting(self, measurement: str) -> list[str]:
        """Wires that report ``measurement`` at one or more heights, sorted."""
        return sorted(
            wire
            for wire, availability in self.wire_availability.items()
            if availability.heights(measurement)
        )


def load_climate_model(yaml_path: Path) -> ClimateModelConfig:
    """Load and validate the ``climate_model`` block from a twin metadata YAML.

    Raises if the file or the key is absent, or if any value is missing — the
    model must never train on implicit defaults.
    """
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if "climate_model" not in raw:
        raise ValueError(f"no 'climate_model' block in {yaml_path}")
    return ClimateModelConfig(**raw["climate_model"])
