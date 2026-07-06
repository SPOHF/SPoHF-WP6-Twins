"""Tests for the pure crop-climate day view-model builder (no DB).

The builder must return, per growth section, exactly the series the shared risk
metrics produce when called directly on the same frames — the view-model is a
seam, not a second implementation.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from wp6_data.red.db import WIRE_SENSOR_MEASUREMENTS, wire_device_id
from wp6_data.red.growth_sections import GrowthSection
from wp6_data.red.multi_height.view_model import build_crop_climate_day
from wp6_data.red.risk.config import load_risk_thresholds
from wp6_data.red.risk.metrics import (
    compute_cumulative_dli,
    vpd_series,
    wet_hours_series,
)

RED_METADATA = Path(__file__).parent.parent / "src/wp6_data/red/metadata.yaml"
THRESHOLDS = load_risk_thresholds(RED_METADATA)

WIRE = "WS_01_01"
TIMEZONE = "UTC"
DAY = date(2026, 5, 26)
DAY_START = pd.Timestamp(DAY, tz=TIMEZONE)

SECTIONS = [
    GrowthSection(height=1, label="Kop"),
    GrowthSection(height=2, label="Wortels"),
]

# Relative to the configured wet threshold so the fixture tracks the config.
WET_RH = THRESHOLDS.fungal.rh_pct + 5.0
DRY_RH = THRESHOLDS.fungal.rh_pct - 10.0

DAY_TIMES = [DAY_START + pd.Timedelta(hours=12, minutes=m) for m in (0, 15, 30)]
# Pre-day look-back readings: inside the fetched window, before the shown day.
LOOKBACK_TIMES = [DAY_START - pd.Timedelta(hours=h) for h in (2, 1)]


def _rows(device, height, measurement, times, values):
    return [
        {"device": device, "height": height, "measurement": measurement,
         "time": t, "value": v}
        for t, v in zip(times, values, strict=True)
    ]


@pytest.fixture
def readings() -> pd.DataFrame:
    rows = []
    for height, par, temp, hum, co2 in (
        (1, [100.0, 110.0, 120.0], [25.0, 26.0, 25.5], [WET_RH] * 3,
         [500.0, 480.0, 470.0]),
        (2, [50.0, 60.0, 70.0], [22.0, 23.0, 24.0], [DRY_RH] * 3,
         [600.0, 610.0, 620.0]),
    ):
        device = wire_device_id(WIRE, height)
        rows += _rows(device, height, "par", DAY_TIMES, par)
        rows += _rows(device, height, "temp", DAY_TIMES, temp)
        rows += _rows(device, height, "hum", DAY_TIMES, hum)
        rows += _rows(device, height, "co2", DAY_TIMES, co2)
        rows += _rows(device, height, "hum", LOOKBACK_TIMES, [WET_RH, WET_RH])
    return pd.DataFrame(rows)


def _build(readings):
    return build_crop_climate_day(
        readings, WIRE, SECTIONS, THRESHOLDS, TIMEZONE, target_date=DAY,
    )


def _device_day(readings, height):
    """The one-device day frame, as the page would scope it."""
    device = wire_device_id(WIRE, height)
    d = readings[readings["device"] == device]
    return d[(d["time"] >= DAY_START) & (d["time"] < DAY_START + pd.Timedelta(days=1))]


class TestBuildCropClimateDay:
    def test_day_start_and_section_order(self, readings):
        vm = _build(readings)
        assert vm.day_start == DAY_START
        assert [(s.height, s.label) for s in vm.sections] == [
            (sec.height, sec.label) for sec in SECTIONS
        ]

    def test_measured_series_are_day_scoped_and_time_sorted(self, readings):
        vm = _build(readings)
        for section in vm.sections:
            day_df = _device_day(readings, section.height)
            for m in WIRE_SENSOR_MEASUREMENTS:
                expected = (
                    day_df[day_df["measurement"] == m].sort_values("time")["value"].tolist()
                )
                assert section.series[m] == expected
        # The look-back hum readings are excluded from the shown day's series.
        assert vm.sections[0].series["hum"] == [WET_RH] * len(DAY_TIMES)

    def test_height_dli_matches_metric(self, readings):
        vm = _build(readings)
        for section in vm.sections:
            day_df = _device_day(readings, section.height)
            cum = compute_cumulative_dli(
                day_df[day_df["measurement"] == "par"][["time", "value"]]
            )
            assert section.height_dli == cum["cumulative_dli"].tolist()

    def test_vpd_matches_metric(self, readings):
        vm = _build(readings)
        for section in vm.sections:
            expected = vpd_series(_device_day(readings, section.height))["value"].tolist()
            assert expected  # temp + hum present, so the series is non-trivial
            assert section.vpd == expected

    def test_fungal_accumulates_lookback_then_trims_to_day(self, readings):
        vm = _build(readings)
        device = wire_device_id(WIRE, 1)
        hum_window = readings[
            (readings["device"] == device) & (readings["measurement"] == "hum")
        ][["time", "value"]]
        w = wet_hours_series(
            hum_window, THRESHOLDS.fungal.rh_pct, THRESHOLDS.fungal.window_hours,
        )
        expected = w[w["time"] >= DAY_START]["value"].tolist()
        assert vm.sections[0].fungal == expected
        # The look-back points fed the accumulation but are not drawn.
        assert len(vm.sections[0].fungal) == len(DAY_TIMES) < len(w)
        # Wet look-back hours are counted, so the day starts above zero.
        assert vm.sections[0].fungal[0] > 0

    def test_bounds_span_latest_values_across_sections(self, readings):
        vm = _build(readings)
        for m in WIRE_SENSOR_MEASUREMENTS:
            latests = [s.series[m][-1] for s in vm.sections if s.series[m]]
            assert vm.bounds[m] == (min(latests), max(latests))

    def test_bounds_default_when_measurement_absent(self, readings):
        no_co2 = readings[readings["measurement"] != "co2"]
        vm = _build(no_co2)
        assert vm.bounds["co2"] == (0.0, 1.0)

    def test_pure_builder_carries_no_persisted_state(self, readings):
        vm = _build(readings)
        assert vm.state_by_height == {}
        assert vm.as_of is None
