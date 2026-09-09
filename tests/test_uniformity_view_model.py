"""Tests for the pure cross-wire uniformity view-model (no DB).

The builder must not invent climate maths — it reads the per-wire crop-climate
builder and only pivots, compares and classifies. What is pinned here is
therefore the *comparison*: what counts as a spread, what a partly-reporting
wire does to it, and when a disagreement is an offset rather than a divergence.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from wp6_data.red.db import wire_device_id
from wp6_data.red.growth_sections import GrowthSection
from wp6_data.red.multi_height.config import (
    CROP_METRICS,
    METRIC_SOURCES,
    UniformityConfig,
    load_uniformity_config,
)
from wp6_data.red.multi_height.uniformity import (
    DELTA_SHARE_OF_SPREAD,
    VERDICT_AGREES,
    VERDICT_DIVERGENT,
    VERDICT_EXCLUDED,
    VERDICT_OFFSET,
    aggregate,
    build_uniformity_day,
)
from wp6_data.red.risk.config import load_risk_thresholds

RED_METADATA = Path(__file__).parent.parent / "src/wp6_data/red/metadata.yaml"
THRESHOLDS = load_risk_thresholds(RED_METADATA)
CONFIG = load_uniformity_config(RED_METADATA)

TIMEZONE = "UTC"
DAY = date(2026, 8, 12)
DAY_START = pd.Timestamp(DAY, tz=TIMEZONE)

WIRES = ["WS_01_01", "WS_01_02", "WS_01_03"]
SECTIONS = [
    GrowthSection(height=1, label="Head"),
    GrowthSection(height=2, label="Flowering"),
    GrowthSection(height=3, label="Fruit set"),
]

# Comfortably above the configured minimum, so coverage is never the variable
# under test unless a case deliberately makes it so.
FULL_HOURS = int(CONFIG.min_coverage_hours) + 6
SPARSE_HOURS = int(CONFIG.min_coverage_hours) - 6
NOTABLE_TEMP = CONFIG.notable_spread["temp"]

BASE_TEMP = 20.0


def _hourly(hours: int) -> list[pd.Timestamp]:
    """One reading on the hour, from local midnight — so coverage == len."""
    return [DAY_START + pd.Timedelta(hours=h) for h in range(hours)]


def _frame(temp_by_wire_height, hours_by_wire=None) -> pd.DataFrame:
    """Readings where each (wire, height) holds a flat temperature all day.

    Flat on purpose: the mean is then exactly the declared value, so a test
    about *comparison* never turns into a test about averaging.
    """
    hours_by_wire = hours_by_wire or {}
    rows = []
    for (wire, height), temp in temp_by_wire_height.items():
        times = _hourly(hours_by_wire.get(wire, FULL_HOURS))
        device = wire_device_id(wire, height)
        rows += [
            {"device": device, "height": height, "measurement": "temp",
             "time": t, "value": temp}
            for t in times
        ]
    return pd.DataFrame(
        rows,
        columns=["device", "height", "measurement", "time", "value"],
    )


def _flat(offsets: dict[str, float], hours_by_wire=None) -> pd.DataFrame:
    """Every wire flat at ``BASE_TEMP + offsets[wire]``, at every height."""
    return _frame(
        {
            (wire, section.height): BASE_TEMP + offset
            for wire, offset in offsets.items()
            for section in SECTIONS
        },
        hours_by_wire=hours_by_wire,
    )


def _build(df, metric="temp", wires=None, config=None):
    return build_uniformity_day(
        df, wires or WIRES, SECTIONS, THRESHOLDS, config or CONFIG,
        metric, TIMEZONE, target_date=DAY,
    )


def _verdict(vm, wire):
    return next(v for v in vm.verdicts if v.wire == wire)


class TestConfig:
    def test_red_metadata_declares_every_metric(self):
        assert set(CONFIG.notable_spread) >= set(CROP_METRICS)

    def test_missing_block_raises(self, tmp_path):
        path = tmp_path / "metadata.yaml"
        path.write_text("devices: {}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no 'uniformity' block"):
            load_uniformity_config(path)

    def test_incomplete_notable_spread_raises(self, tmp_path):
        path = tmp_path / "metadata.yaml"
        path.write_text(
            "uniformity:\n  min_coverage_hours: 12\n  notable_spread:\n    temp: 1.0\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="notable_spread is missing"):
            load_uniformity_config(path)


class TestAggregate:
    def test_instantaneous_metrics_take_the_day_mean(self):
        assert aggregate([10.0, 20.0, 30.0], "temp") == 20.0

    def test_height_dli_takes_the_last_of_the_cumulative_series(self):
        assert aggregate([1.0, 5.0, 9.0], "dli") == 9.0

    def test_fungal_wet_hours_take_the_peak(self):
        assert aggregate([1.0, 7.0, 3.0], "fungal") == 7.0

    def test_no_readings_aggregate_to_none(self):
        assert aggregate([], "temp") is None


class TestSpread:
    def test_spread_is_max_minus_min_across_wires(self):
        vm = _build(_flat({"WS_01_01": 0.0, "WS_01_02": 2.0, "WS_01_03": 0.5}))

        row = vm.rows[0]
        assert row.spread == pytest.approx(2.0)
        assert row.median == pytest.approx(BASE_TEMP + 0.5)
        assert [c.aggregate for c in row.cells] == pytest.approx(
            [BASE_TEMP, BASE_TEMP + 2.0, BASE_TEMP + 0.5]
        )

    def test_rows_follow_declared_section_order(self):
        vm = _build(_flat({w: 0.0 for w in WIRES}))

        assert [r.height for r in vm.rows] == [s.height for s in SECTIONS]
        assert [r.label for r in vm.rows] == [s.label for s in SECTIONS]
        assert vm.wires == WIRES

    def test_cells_carry_both_the_aggregate_and_the_latest(self):
        rising = _frame({("WS_01_01", 1): 0.0})
        # Overwrite with a series that moves, so the two numbers must differ.
        rising.loc[:, "value"] = [float(i) for i in range(len(rising))]
        vm = _build(rising, wires=["WS_01_01"])

        cell = vm.rows[0].cells[0]
        assert cell.latest == pytest.approx(float(FULL_HOURS - 1))
        assert cell.aggregate == pytest.approx(sum(range(FULL_HOURS)) / FULL_HOURS)

    def test_one_wire_alone_has_no_spread(self):
        vm = _build(_flat({"WS_01_01": 0.0}), wires=["WS_01_01"])

        assert all(r.spread is None for r in vm.rows)
        # And it must not congratulate itself on agreeing with nobody.
        assert _verdict(vm, "WS_01_01").kind == VERDICT_EXCLUDED

    def test_worst_spread_reports_the_widest_section(self):
        vm = _build(_frame({
            ("WS_01_01", 1): BASE_TEMP, ("WS_01_02", 1): BASE_TEMP + 1.0,
            ("WS_01_01", 2): BASE_TEMP, ("WS_01_02", 2): BASE_TEMP + 4.0,
            ("WS_01_01", 3): BASE_TEMP, ("WS_01_02", 3): BASE_TEMP,
        }), wires=["WS_01_01", "WS_01_02"])

        assert vm.worst_spread == pytest.approx(4.0)


class TestCoverage:
    def test_a_wire_below_min_coverage_is_excluded_from_the_spread(self):
        vm = _build(_flat(
            {"WS_01_01": 0.0, "WS_01_02": 0.0, "WS_01_03": 10.0},
            hours_by_wire={"WS_01_03": SPARSE_HOURS},
        ))

        row = vm.rows[0]
        sparse = row.cells[2]
        assert sparse.comparable is False
        assert sparse.coverage_hours == SPARSE_HOURS
        # Its 10 °C outlier must not widen the spread of the two that reported.
        assert row.spread == pytest.approx(0.0)

    def test_an_excluded_wire_still_carries_its_reading(self):
        vm = _build(_flat(
            {"WS_01_01": 0.0, "WS_01_02": 0.0, "WS_01_03": 10.0},
            hours_by_wire={"WS_01_03": SPARSE_HOURS},
        ))

        sparse = vm.rows[0].cells[2]
        assert sparse.aggregate == pytest.approx(BASE_TEMP + 10.0)
        assert sparse.series

    def test_an_excluded_wire_gets_the_excluded_verdict(self):
        vm = _build(_flat(
            {"WS_01_01": 0.0, "WS_01_02": 0.0, "WS_01_03": 0.0},
            hours_by_wire={"WS_01_03": SPARSE_HOURS},
        ))

        verdict = _verdict(vm, "WS_01_03")
        assert verdict.kind == VERDICT_EXCLUDED
        assert verdict.coverage_hours == SPARSE_HOURS
        assert vm.comparable_wires == ["WS_01_01", "WS_01_02"]

    def test_a_wire_that_never_reported_is_excluded_not_absent(self):
        vm = _build(_flat({"WS_01_01": 0.0, "WS_01_02": 0.0}))

        assert _verdict(vm, "WS_01_03").kind == VERDICT_EXCLUDED
        assert vm.rows[0].cells[2].coverage_hours == 0
        assert vm.rows[0].cells[2].aggregate is None
        # It still occupies a column, so the page cannot silently lose a wire.
        assert len(vm.rows[0].cells) == len(WIRES)


class TestVerdicts:
    def test_a_uniform_drift_at_every_height_reads_as_an_offset(self):
        drift = NOTABLE_TEMP * 2
        vm = _build(_flat({"WS_01_01": 0.0, "WS_01_02": drift, "WS_01_03": 0.0}))

        verdict = _verdict(vm, "WS_01_02")
        assert verdict.kind == VERDICT_OFFSET
        assert verdict.offset == pytest.approx(drift)

    def test_one_height_out_of_line_reads_as_divergent(self):
        vm = _build(_frame({
            ("WS_01_01", 1): BASE_TEMP, ("WS_01_02", 1): BASE_TEMP,
            ("WS_01_01", 2): BASE_TEMP, ("WS_01_02", 2): BASE_TEMP,
            # Only the third section disagrees, and by more than the threshold.
            ("WS_01_01", 3): BASE_TEMP,
            ("WS_01_02", 3): BASE_TEMP + NOTABLE_TEMP * 4,
        }), wires=["WS_01_01", "WS_01_02"])

        verdict = _verdict(vm, "WS_01_02")
        assert verdict.kind == VERDICT_DIVERGENT
        assert verdict.worst_height == SECTIONS[2].height

    def test_wires_within_the_notable_spread_agree(self):
        nudge = NOTABLE_TEMP / 4
        vm = _build(_flat({"WS_01_01": 0.0, "WS_01_02": nudge, "WS_01_03": -nudge}))

        assert {_verdict(vm, w).kind for w in WIRES} == {VERDICT_AGREES}

    def test_the_threshold_is_the_configured_notable_spread(self):
        """Halving the config must flip an agreeing wire to an offset."""
        drift = NOTABLE_TEMP * DELTA_SHARE_OF_SPREAD * 0.6
        df = _flat({"WS_01_01": 0.0, "WS_01_02": drift, "WS_01_03": 0.0})
        strict = UniformityConfig(
            min_coverage_hours=CONFIG.min_coverage_hours,
            notable_spread={**CONFIG.notable_spread, "temp": NOTABLE_TEMP / 2},
        )

        assert _verdict(_build(df), "WS_01_02").kind == VERDICT_AGREES
        assert _verdict(_build(df, config=strict), "WS_01_02").kind == VERDICT_OFFSET

    def test_a_notable_spread_between_two_wires_is_never_called_agreement(self):
        """The Spread column and the verdicts must tell one story.

        Two wires sit either side of their own median, so each is only half the
        spread away from it. Judging those halves against a whole spread let a
        column flagged as notable be summarised as "agrees".
        """
        df = _flat({"WS_01_01": 0.0, "WS_01_02": NOTABLE_TEMP})
        vm = _build(df, wires=["WS_01_01", "WS_01_02"])

        assert vm.rows[0].spread == pytest.approx(NOTABLE_TEMP)
        assert {_verdict(vm, w).kind for w in ("WS_01_01", "WS_01_02")} == {
            VERDICT_OFFSET
        }

    def test_notable_spread_is_carried_for_the_legend(self):
        vm = _build(_flat({w: 0.0 for w in WIRES}))

        assert vm.notable_spread == NOTABLE_TEMP


class TestEmptyDay:
    def test_a_day_with_no_readings_renders_rather_than_raises(self):
        empty = pd.DataFrame(
            columns=["device", "height", "measurement", "time", "value"],
        ).astype({"time": "datetime64[ns, UTC]", "value": "float64"})

        vm = _build(empty)

        assert vm.day_start == DAY_START
        assert [r.height for r in vm.rows] == [s.height for s in SECTIONS]
        assert all(r.spread is None and r.median is None for r in vm.rows)
        assert {v.kind for v in vm.verdicts} == {VERDICT_EXCLUDED}
        assert vm.worst_spread is None


class TestMetricAwareCoverage:
    """Coverage counts the metric's own parents, never the busy device.

    The wires do not all report the same four measurements: one may stream PAR
    all day and no temperature at all. Counting rows per device would credit it
    with having observed a temperature it never took.
    """

    def test_every_metric_declares_its_sources(self):
        assert set(METRIC_SOURCES) == set(CROP_METRICS)

    def test_a_wire_busy_with_another_measurement_gets_no_temp_coverage(self):
        par_only = pd.DataFrame(
            [
                {"device": wire_device_id("WS_01_02", SECTIONS[0].height),
                 "height": SECTIONS[0].height, "measurement": "par",
                 "time": t, "value": 300.0}
                for t in _hourly(FULL_HOURS)
            ],
            columns=["device", "height", "measurement", "time", "value"],
        )
        df = pd.concat([_flat({"WS_01_01": 0.0}), par_only], ignore_index=True)

        vm = _build(df, wires=["WS_01_01", "WS_01_02"])

        busy = vm.rows[0].cells[1]
        assert busy.coverage_hours == 0
        assert busy.comparable is False
        assert _verdict(vm, "WS_01_02").kind == VERDICT_EXCLUDED

    def test_vpd_counts_only_hours_both_parents_reported(self):
        height = SECTIONS[0].height
        device = wire_device_id("WS_01_01", height)
        rows = [
            {"device": device, "height": height, "measurement": "temp",
             "time": t, "value": 22.0}
            for t in _hourly(FULL_HOURS)
        ]
        # Humidity stops early, so VPD is only derivable for the overlap.
        overlap = FULL_HOURS - 4
        rows += [
            {"device": device, "height": height, "measurement": "hum",
             "time": t, "value": 60.0}
            for t in _hourly(overlap)
        ]
        df = pd.DataFrame(
            rows, columns=["device", "height", "measurement", "time", "value"],
        )

        vm = _build(df, metric="vpd", wires=["WS_01_01"])
        assert vm.rows[0].cells[0].coverage_hours == overlap

        # The same readings give temperature its full day — one parent, not two.
        vm_temp = _build(df, metric="temp", wires=["WS_01_01"])
        assert vm_temp.rows[0].cells[0].coverage_hours == FULL_HOURS


class TestVerdictScope:
    def test_coverage_reported_is_the_wires_best_section(self):
        """One dead height must not speak for a wire that reported elsewhere."""
        readings = _flat({"WS_01_01": 0.0, "WS_01_02": 0.0})
        dead = wire_device_id("WS_01_02", SECTIONS[-1].height)
        df = readings[readings["device"] != dead]

        verdict = _verdict(_build(df, wires=["WS_01_01", "WS_01_02"]), "WS_01_02")

        assert verdict.coverage_hours == FULL_HOURS
        assert verdict.kind != VERDICT_EXCLUDED

    def test_a_verdict_says_how_many_sections_it_rests_on(self):
        readings = _flat({"WS_01_01": 0.0, "WS_01_02": 0.0})
        # Only the first section survives on the second wire.
        kept = {wire_device_id("WS_01_02", SECTIONS[0].height)}
        df = readings[
            readings["device"].str.startswith("WS_01_01")
            | readings["device"].isin(kept)
        ]

        vm = _build(df, wires=["WS_01_01", "WS_01_02"])

        assert _verdict(vm, "WS_01_02").sections_compared == 1
        assert _verdict(vm, "WS_01_01").sections_compared == 1

    def test_a_full_profile_compares_every_section(self):
        vm = _build(_flat({"WS_01_01": 0.0, "WS_01_02": 0.0}))

        assert _verdict(vm, "WS_01_01").sections_compared == len(SECTIONS)

    def test_an_excluded_wire_compares_nothing(self):
        vm = _build(_flat({"WS_01_01": 0.0, "WS_01_02": 0.0}))

        assert _verdict(vm, "WS_01_03").sections_compared == 0
