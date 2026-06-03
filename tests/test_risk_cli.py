"""Tests for the wp6-red-eval-risk CLI's pure parts (issue 014)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from wp6_data.red.risk.cli import _parse_args, format_evaluation
from wp6_data.red.risk.engine import RiskEpisodeRecord, RiskEvaluation, SectionState


class TestParseArgs:
    def test_defaults_are_none(self):
        ns = _parse_args([])
        assert ns.wire is None and ns.start is None and ns.end is None

    def test_parses_wire_and_dates(self):
        ns = _parse_args(["--wire", "WS_01_01", "--start", "2026-05-01", "--end", "2026-05-07"])
        assert ns.wire == "WS_01_01"
        assert ns.start == date(2026, 5, 1)
        assert ns.end == date(2026, 5, 7)


class TestFormatEvaluation:
    def _result(self):
        return RiskEvaluation(
            states=[SectionState(
                height=1, label="Kop", height_dli=0.5, vpd_latest=2.0,
                vpd_in_band=False, wet_hours_latest=3.0, fungal_active=True,
                canopy_deficit=True,
            )],
            episodes=[RiskEpisodeRecord(
                height=1, label="Kop", risk="fungal",
                start=pd.Timestamp("2026-05-26T12:00:00", tz="UTC"),
                end=None, peak=3.0, thresholds={"rh_pct": 85},
            )],
        )

    def test_renders_state_flags(self):
        out = format_evaluation(self._result(), "WS_01_01", date(2026, 5, 1), date(2026, 5, 7))
        assert "WS_01_01" in out
        for flag in ("FUNGAL", "VPD-OOB", "LIGHT-DEFICIT"):
            assert flag in out

    def test_renders_open_episode_as_ongoing(self):
        out = format_evaluation(self._result(), "WS_01_01", date(2026, 5, 1), date(2026, 5, 7))
        assert "fungal" in out
        assert "ongoing" in out
        assert "Episodes (1)" in out
