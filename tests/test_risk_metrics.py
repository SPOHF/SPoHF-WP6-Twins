"""Tests for the red risk config loader and pure metric functions (issue 014)."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from wp6_data.red.risk.config import load_risk_thresholds
from wp6_data.red.risk.metrics import (
    compute_dli,
    saturation_vapor_pressure_kpa,
    vpd_kpa,
    vpd_series,
    wet_hours_series,
)

RED_METADATA = Path(__file__).parent.parent / "src/wp6_data/red/metadata.yaml"


def _ts(*, h: int, m: int = 0) -> pd.Timestamp:
    return pd.Timestamp(f"2026-05-26T{h:02d}:{m:02d}:00", tz="UTC")


class TestLoadRiskThresholds:
    def test_loads_shipped_block(self):
        t = load_risk_thresholds(RED_METADATA)
        assert t.fungal.rh_pct > 0
        assert t.vpd.band_min_kpa < t.vpd.band_max_kpa
        assert t.canopy_dli.target_mol > 0
        assert t.episode.min_duration_minutes > 0

    def test_missing_block_raises(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("devices: {}\n")
        with pytest.raises(ValueError, match="risk_thresholds"):
            load_risk_thresholds(p)

    def test_missing_field_raises(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("risk_thresholds:\n  fungal:\n    rh_pct: 85\n")
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            load_risk_thresholds(p)


class TestHeightDli:
    def test_two_point_integral(self):
        # 100 µmol over a 15-min interval (within the gap clip) -> 100*900/1e6.
        df = pd.DataFrame(
            {"time": [_ts(h=12), _ts(h=12, m=15)], "value": [100.0, 100.0]}
        )
        assert compute_dli(df) == pytest.approx(100.0 * 900 / 1_000_000)

    def test_too_few_readings_is_none(self):
        df = pd.DataFrame({"time": [_ts(h=12)], "value": [100.0]})
        assert compute_dli(df) is None


class TestVpd:
    def test_saturated_air_has_zero_deficit(self):
        assert vpd_kpa(20.0, 100.0) == pytest.approx(0.0, abs=1e-9)

    def test_half_humidity_is_half_of_svp(self):
        assert vpd_kpa(20.0, 50.0) == pytest.approx(
            saturation_vapor_pressure_kpa(20.0) * 0.5
        )

    def test_svp_matches_tetens(self):
        assert saturation_vapor_pressure_kpa(20.0) == pytest.approx(
            0.6108 * math.exp((17.27 * 20.0) / (20.0 + 237.3))
        )

    def test_series_aligns_temp_and_hum(self):
        df = pd.DataFrame({
            "time": [_ts(h=12), _ts(h=12), _ts(h=13), _ts(h=13)],
            "measurement": ["temp", "hum", "temp", "hum"],
            "value": [20.0, 50.0, 25.0, 60.0],
        })
        out = vpd_series(df)
        assert list(out["time"]) == [_ts(h=12), _ts(h=13)]
        assert out["value"].iloc[0] == pytest.approx(vpd_kpa(20.0, 50.0))

    def test_series_empty_without_both_measurements(self):
        df = pd.DataFrame({
            "time": [_ts(h=12)], "measurement": ["temp"], "value": [20.0],
        })
        assert vpd_series(df).empty


class TestWetHours:
    def test_accumulates_wet_intervals(self):
        # 90,90,50 %RH at 12:00,13:00,14:00; threshold 85 -> two wet hours by
        # 13:00. max_gap raised to 1h so the hourly fixture isn't gap-clipped.
        df = pd.DataFrame({
            "time": [_ts(h=12), _ts(h=13), _ts(h=14)],
            "value": [90.0, 90.0, 50.0],
        })
        out = wet_hours_series(
            df, rh_pct=85.0, window_hours=24.0, max_gap_seconds=3600,
        )
        assert out["value"].tolist() == pytest.approx([1.0, 2.0, 2.0])

    def test_dry_series_stays_zero(self):
        df = pd.DataFrame({
            "time": [_ts(h=12), _ts(h=13)], "value": [50.0, 60.0],
        })
        out = wet_hours_series(df, rh_pct=85.0, window_hours=24.0)
        assert out["value"].tolist() == pytest.approx([0.0, 0.0])

    def test_empty_in_empty_out(self):
        assert wet_hours_series(
            pd.DataFrame(columns=["time", "value"]), rh_pct=85.0, window_hours=24.0,
        ).empty
