"""Tests for the red risk engine (issue 014)."""

from __future__ import annotations

import pandas as pd

from wp6_data.red.db import wire_device_id
from wp6_data.red.growth_sections import GrowthSection
from wp6_data.red.risk.config import (
    CanopyDli,
    EpisodeConfig,
    FungalThresholds,
    RiskThresholds,
    VpdBand,
)
from wp6_data.red.risk.engine import evaluate

BASE = pd.Timestamp("2026-05-26T12:00:00", tz="UTC")
SECTIONS = [GrowthSection(height=h, label=f"H{h}") for h in (1, 2, 3, 4, 5)]
THRESHOLDS = RiskThresholds(
    fungal=FungalThresholds(rh_pct=85.0, window_hours=24.0, active_wet_hours=1.0),
    vpd=VpdBand(band_min_kpa=0.4, band_max_kpa=1.2),
    canopy_dli=CanopyDli(target_mol=22.0),
    episode=EpisodeConfig(min_duration_minutes=30.0),
)


def _wire_df(specs):
    """specs: (height, measurement, [values]) sampled every 15 min from BASE."""
    rows = []
    for height, meas, values in specs:
        for i, v in enumerate(values):
            rows.append({
                "device": wire_device_id("WS_01_01", height),
                "height": height,
                "measurement": meas,
                "time": BASE + pd.Timedelta(minutes=15 * i),
                "value": float(v),
            })
    return pd.DataFrame(rows)


def _state(result, height):
    return next(s for s in result.states if s.height == height)


def _eval():
    df = _wire_df([
        (1, "par", [50.0] * 12),               # canopy: very low light -> deficit
        (2, "hum", [90.0] * 12),               # sustained high RH -> fungal
        (3, "temp", [35.0] * 12),              # hot + dry -> VPD far above band
        (3, "hum", [20.0] * 12),
    ])
    return evaluate(df, SECTIONS, THRESHOLDS)


class TestStates:
    def test_one_state_per_section(self):
        assert {s.height for s in _eval().states} == {s.height for s in SECTIONS}

    def test_canopy_deficit_only_on_top_section(self):
        result = _eval()
        assert _state(result, 1).canopy_deficit is True
        assert _state(result, 2).canopy_deficit is None  # not the canopy section

    def test_fungal_active_on_humid_height(self):
        assert _state(_eval(), 2).fungal_active is True

    def test_vpd_out_of_band_on_hot_dry_height(self):
        assert _state(_eval(), 3).vpd_in_band is False


class TestEpisodes:
    def test_emits_each_risk_kind(self):
        risks = {(e.risk, e.height) for e in _eval().episodes}
        assert ("canopy", 1) in risks
        assert ("fungal", 2) in risks
        assert ("vpd", 3) in risks

    def test_episodes_are_stamped_with_thresholds(self):
        fungal = next(e for e in _eval().episodes if e.risk == "fungal")
        assert fungal.thresholds["rh_pct"] == THRESHOLDS.fungal.rh_pct

    def test_quiet_data_yields_no_episodes(self):
        # In-band VPD, dry air, ample canopy light -> nothing fires.
        df = _wire_df([
            (1, "par", [2500.0] * 12),          # integrates above the 22 mol target
            (2, "temp", [22.0] * 12),           # VPD ~0.9 kPa, in band
            (2, "hum", [65.0] * 12),
        ])
        assert evaluate(df, SECTIONS, THRESHOLDS).episodes == []

    def test_no_sections_is_empty(self):
        assert evaluate(_wire_df([(1, "par", [50.0] * 12)]), [], THRESHOLDS).episodes == []
