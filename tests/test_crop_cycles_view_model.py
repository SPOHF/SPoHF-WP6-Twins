"""Tests for the pure half of the red crop-cycles view model.

Covers attachment (which cohort a measurement belongs to) and coverage (how much
of a cohort's window the climate actually spans) — the two pieces of logic the
picture depends on and the eye cannot check.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from wp6_data.red.crop_cycles.config import load_crop_cycles, to_cohort_spec, to_cycle_spec
from wp6_data.red.crop_cycles.view_model import build_waterfall
from wp6_data.shared.cycles import generate_cohorts

RED_METADATA = Path(__file__).parent.parent / "src/wp6_data/red/metadata.yaml"
CONFIG = load_crop_cycles(RED_METADATA)
SPEC = to_cohort_spec(CONFIG)
CYCLE = CONFIG.cycles[0]
COHORTS = generate_cohorts(to_cycle_spec(CYCLE), SPEC)

DEVICES = {"dev-a": "Alpha", "dev-b": "Beta"}


def _daily(start: date, days: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(days)],
            "value": [20.0] * days,
        }
    )


def _full_daily() -> pd.DataFrame:
    return _daily(CYCLE.start, (CYCLE.end - CYCLE.start).days)


def _obs(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "device", "value"])


class TestAttachment:
    def test_measurement_lands_on_the_cohort_that_set_a_duration_earlier(self):
        target = COHORTS[5]
        observed = target.end  # first day of its completion window
        view = build_waterfall(
            COHORTS, SPEC, _obs([(observed, "dev-a", 4.2)]), _full_daily(),
            device_labels=DEVICES,
        )
        measured = view.measured
        assert len(measured) == 1
        assert measured[0].cohort.key == target.key
        assert measured[0].cohort.start == observed - SPEC.duration
        assert not view.unattached

    def test_measurement_outside_every_cohort_is_reported_not_dropped(self):
        stray = CYCLE.start  # before any cohort has completed
        view = build_waterfall(
            COHORTS, SPEC, _obs([(stray, "dev-a", 4.2)]), _full_daily(),
            device_labels=DEVICES,
        )
        assert not view.measured
        assert [(u.day, u.device) for u in view.unattached] == [(stray, "dev-a")]

    def test_every_cohort_becomes_a_lane_even_when_unmeasured(self):
        view = build_waterfall(
            COHORTS, SPEC, _obs([]), _full_daily(), device_labels=DEVICES,
        )
        assert len(view.lanes) == len(COHORTS)
        assert not view.measured

    def test_lane_group_is_the_cycle_label(self):
        view = build_waterfall(
            COHORTS, SPEC, _obs([]), _full_daily(), device_labels=DEVICES,
        )
        assert {lane.group for lane in view.lanes} == {CYCLE.label}


class TestVarieties:
    def test_both_cultivars_share_one_lane_as_paired_markers(self):
        observed = COHORTS[5].end
        view = build_waterfall(
            COHORTS, SPEC,
            _obs([(observed, "dev-a", 4.2), (observed, "dev-b", 3.8)]),
            _full_daily(), device_labels=DEVICES,
        )
        assert len(view.measured) == 1
        markers = view.measured[0].markers
        assert {m.series for m in markers} == {"Alpha", "Beta"}
        assert {m.value for m in markers} == {4.2, 3.8}

    def test_a_single_cultivar_drops_the_series_tag(self):
        observed = COHORTS[5].end
        view = build_waterfall(
            COHORTS, SPEC, _obs([(observed, "dev-a", 4.2)]), _full_daily(),
            device_labels=DEVICES,
        )
        assert [m.series for m in view.measured[0].markers] == [""]

    def test_unknown_device_falls_back_to_its_id(self):
        observed = COHORTS[5].end
        view = build_waterfall(
            COHORTS, SPEC, _obs([(observed, "mystery", 4.2)]), _full_daily(),
            device_labels=DEVICES,
        )
        assert view.measured[0].markers[0].label == "mystery"


class TestCoverage:
    def test_full_climate_leaves_every_lane_unfaded(self):
        view = build_waterfall(
            COHORTS, SPEC, _obs([]), _full_daily(), device_labels=DEVICES,
        )
        assert not view.partial

    def test_climate_starting_late_fades_the_early_lanes(self):
        # Climate that only begins once the season is underway, as red's real
        # sensors do relative to the first Sijia season.
        late = _daily(COHORTS[4].start, (CYCLE.end - COHORTS[4].start).days)
        view = build_waterfall(
            COHORTS, SPEC, _obs([]), late, device_labels=DEVICES,
        )
        assert view.partial
        assert view.lanes[0].coverage < view.lanes[-1].coverage

    def test_no_climate_at_all_gives_zero_coverage(self):
        view = build_waterfall(
            COHORTS, SPEC, _obs([]), pd.DataFrame(), device_labels=DEVICES,
        )
        assert all(lane.coverage == 0.0 for lane in view.lanes)
        assert len(view.partial) == len(view.lanes)
