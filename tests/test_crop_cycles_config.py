"""Tests for red's crop-cycle config loader and its conversion to shared types."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from wp6_data.red.crop_cycles.config import (
    load_crop_cycles,
    to_cohort_spec,
    to_cycle_spec,
)

RED_METADATA = Path(__file__).parent.parent / "src/wp6_data/red/metadata.yaml"

MINIMAL = """
crop_cycles:
  cohort:
    interval_days: 7
    duration_weeks: 8
  climate:
    metrics:
      - key: temp
        label: Temp
        unit: "C"
        device: dev-1
        sensor: temp
        agg: mean
  cycles:
    - label: "one"
      start: 2025-06-16
      end: 2025-12-08
"""


class TestLoadCropCycles:
    def test_loads_the_real_red_block(self):
        config = load_crop_cycles(RED_METADATA)
        assert config.cohort.interval_days > 0
        assert config.cycles
        assert config.climate.metrics

    def test_missing_block_raises(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("devices: {}\n")
        with pytest.raises(ValueError, match="no 'crop_cycles' block"):
            load_crop_cycles(p)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no metadata file"):
            load_crop_cycles(tmp_path / "nope.yaml")

    def test_omitted_field_raises_rather_than_defaulting(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(MINIMAL.replace("    interval_days: 7\n", ""))
        with pytest.raises(Exception, match="interval_days"):
            load_crop_cycles(p)

    def test_unsupported_agg_raises(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(MINIMAL.replace("agg: mean", "agg: median"))
        with pytest.raises(ValueError, match="unsupported agg"):
            load_crop_cycles(p)


class TestSelectors:
    def test_unknown_metric_key_falls_back_to_the_first(self):
        config = load_crop_cycles(RED_METADATA)
        assert config.metric("nope") == config.climate.metrics[0]


class TestToCohortSpec:
    def test_duration_comes_from_config(self):
        config = load_crop_cycles(RED_METADATA)
        spec = to_cohort_spec(config)
        assert spec.duration == timedelta(weeks=config.cohort.duration_weeks)

    def test_interval_comes_from_config(self):
        config = load_crop_cycles(RED_METADATA)
        spec = to_cohort_spec(config)
        assert spec.interval == timedelta(days=config.cohort.interval_days)

    def test_the_configured_cohorts_actually_overlap(self):
        """A non-overlapping rhythm would make the waterfall pointless."""
        assert to_cohort_spec(load_crop_cycles(RED_METADATA)).overlap > 1


class TestToCycleSpec:
    def test_carries_label_and_dates(self):
        config = load_crop_cycles(RED_METADATA)
        declared = config.cycles[0]
        spec = to_cycle_spec(declared)
        assert (spec.label, spec.start, spec.end) == (
            declared.label, declared.start, declared.end,
        )
