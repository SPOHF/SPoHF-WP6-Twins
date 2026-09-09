"""Crop-cycle config for the red twin.

Red-only config read from the top-level ``crop_cycles`` key in red's
``metadata.yaml`` (the shared metadata registry ignores it, keeping ``shared/``
twin-agnostic). Mirrors ``risk/config.py``: the values are PROVISIONAL — the
cycle dates especially are horticultural assumptions awaiting confirmation from
Neurath/WP1 — so they live in config, never as code constants, and the models
declare **no defaults**: a missing or malformed block fails loudly at load
rather than silently falling back to guessed dates.

The conversion helpers turn red's vocabulary into the twin-agnostic
``shared.cycles`` model. A cohort is a plain span: it used to be subdivided into
developmental stages bound to growth sections, but the boundaries were fixed
offsets from the set date and so said nothing the start date did not, while
spending the chart's colour on a schedule instead of on observed conditions.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel

from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.cycles import CohortSpec, CycleSpec


class CohortConfig(BaseModel):
    """How often a cohort sets, and how long it takes to complete."""

    interval_days: int
    duration_weeks: int


class ClimateMetric(BaseModel):
    """One selectable climate series, as a (device, sensor) pair.

    This *is* the wire-ready seam: because red models wire heights as devices
    (ADR 0001), pointing a metric at a growth section later means changing
    ``device`` to ``WS_01_01-h3``, with no code change and no new abstraction.
    """

    key: str
    label: str
    unit: str
    device: str
    sensor: str
    agg: str


class ClimateConfig(BaseModel):
    metrics: list[ClimateMetric]


class CycleConfig(BaseModel):
    label: str
    start: date
    end: date


class CropCyclesConfig(BaseModel):
    cohort: CohortConfig
    climate: ClimateConfig
    cycles: list[CycleConfig]

    def metric(self, key: str) -> ClimateMetric:
        """The declared climate metric ``key``, or the first one as a fallback."""
        for m in self.climate.metrics:
            if m.key == key:
                return m
        return self.climate.metrics[0]


def load_crop_cycles(yaml_path: Path) -> CropCyclesConfig:
    """Load and validate the ``crop_cycles`` block from a twin metadata YAML.

    Raises if the file or the key is absent, or if any value is missing — the
    view must never run on implicit dates.
    """
    if not yaml_path.exists():
        raise ValueError(f"no metadata file at {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if "crop_cycles" not in raw:
        raise ValueError(f"no 'crop_cycles' block in {yaml_path}")
    config = CropCyclesConfig(**raw["crop_cycles"])

    unknown = [m.key for m in config.climate.metrics if m.agg not in CHART_AGG_FUNCS]
    if unknown:
        raise ValueError(
            f"climate metrics {unknown} declare an unsupported agg; "
            f"expected one of {sorted(CHART_AGG_FUNCS)}"
        )
    return config


def to_cohort_spec(config: CropCyclesConfig) -> CohortSpec:
    """Red's declared cohort rhythm as a twin-agnostic :class:`CohortSpec`."""
    return CohortSpec(
        interval=timedelta(days=config.cohort.interval_days),
        duration=timedelta(weeks=config.cohort.duration_weeks),
    )


def to_cycle_spec(cycle: CycleConfig) -> CycleSpec:
    """One declared cycle as a twin-agnostic :class:`CycleSpec`."""
    return CycleSpec(label=cycle.label, start=cycle.start, end=cycle.end)
