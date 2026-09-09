"""Tests for the twin-agnostic cycle/cohort model.

Deliberately uses neutral vocabulary: this module must stay free of any twin's
domain language, and the tests are the first place a leak would show.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from wp6_data.shared.cycles import (
    Cohort,
    CohortSpec,
    CycleSpec,
    cohort_for_date,
    exposure,
    generate_cohorts,
    overlap_at,
)

INTERVAL = timedelta(days=7)
DURATION = timedelta(weeks=8)


def _spec() -> CohortSpec:
    return CohortSpec(interval=INTERVAL, duration=DURATION)


def _cycle() -> CycleSpec:
    return CycleSpec("test cycle", date(2025, 6, 16), date(2025, 12, 5))


class TestCohortSpec:
    def test_overlap_is_duration_over_interval(self):
        spec = _spec()
        assert spec.overlap == spec.duration // spec.interval

    def test_overlapping_is_the_point(self):
        """A spec whose cohorts never coexist needs no waterfall."""
        assert _spec().overlap > 1

    def test_non_positive_interval_raises(self):
        with pytest.raises(ValueError, match="interval must be positive"):
            CohortSpec(interval=timedelta(0), duration=DURATION)

    def test_non_positive_duration_raises(self):
        with pytest.raises(ValueError, match="duration must be positive"):
            CohortSpec(interval=INTERVAL, duration=timedelta(0))


class TestGenerateCohorts:
    def test_a_cohort_is_an_undivided_span(self):
        """Cohorts carry no developmental stages — see the module docstring."""
        cohort = generate_cohorts(_cycle(), _spec())[0]
        assert not hasattr(cohort, "phases")

    def test_cohort_span_is_the_declared_duration(self):
        spec = _spec()
        cohort = generate_cohorts(_cycle(), spec)[0]
        assert cohort.end == cohort.start + spec.duration

    def test_cohorts_start_on_the_interval_grid(self):
        spec = _spec()
        cohorts = generate_cohorts(_cycle(), spec)
        starts = [c.start for c in cohorts]
        assert starts[0] == _cycle().start
        assert all(
            b - a == spec.interval for a, b in zip(starts, starts[1:], strict=False)
        )

    def test_a_cohort_cut_off_by_the_cycle_end_is_not_emitted(self):
        spec = _spec()
        cycle = _cycle()
        assert all(c.end <= cycle.end for c in generate_cohorts(cycle, spec))

    def test_steady_state_overlap_matches_the_spec(self):
        spec = _spec()
        cohorts = generate_cohorts(_cycle(), spec)
        # A day late enough that every lane which could have started, has.
        midway = cohorts[0].start + spec.duration
        assert len(overlap_at(midway, cohorts)) == spec.overlap


class TestAttachment:
    def test_observation_attaches_to_exactly_one_cohort(self):
        spec = _spec()
        cohorts = generate_cohorts(_cycle(), spec)
        observed = date(2025, 11, 13)
        matches = [
            c for c in cohorts if c.end <= observed < c.end + spec.interval
        ]
        assert len(matches) == 1
        assert cohort_for_date(observed, cohorts, spec.interval) == matches[0]

    def test_attached_cohort_started_a_duration_earlier(self):
        spec = _spec()
        cohorts = generate_cohorts(_cycle(), spec)
        observed = date(2025, 11, 13)
        cohort = cohort_for_date(observed, cohorts, spec.interval)
        assert cohort is not None
        # Snapped to the grid, so within one interval of "duration before".
        offset = (observed - spec.duration) - cohort.start
        assert timedelta(0) <= offset < spec.interval

    def test_date_in_an_inactive_gap_attaches_to_nothing(self):
        spec = _spec()
        cohorts = generate_cohorts(_cycle(), spec)
        assert cohort_for_date(date(2026, 1, 10), cohorts, spec.interval) is None

    def test_date_before_any_cohort_completed_attaches_to_nothing(self):
        spec = _spec()
        cohorts = generate_cohorts(_cycle(), spec)
        assert cohort_for_date(_cycle().start, cohorts, spec.interval) is None


class TestOverlapAt:
    def test_excludes_the_exclusive_end(self):
        cohort = Cohort("c", "k", "l", date(2025, 1, 1), date(2025, 1, 8))
        assert overlap_at(date(2025, 1, 7), [cohort]) == [cohort]
        assert overlap_at(date(2025, 1, 8), [cohort]) == []


class TestExposure:
    @staticmethod
    def _daily(start: date, days: int, value: float = 20.0) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": [start + timedelta(days=i) for i in range(days)],
                "value": [value] * days,
            }
        )

    def test_full_window_is_fully_covered(self):
        start, end = date(2025, 1, 1), date(2025, 1, 11)
        value, coverage = exposure(start, end, self._daily(start, 10, 21.0))
        assert value == pytest.approx(21.0)
        assert coverage == pytest.approx(1.0)

    def test_half_the_days_missing_halves_coverage(self):
        start, end = date(2025, 1, 1), date(2025, 1, 11)
        value, coverage = exposure(start, end, self._daily(start, 5))
        assert coverage == pytest.approx(0.5)
        assert value is not None

    def test_empty_window_is_none_not_zero(self):
        start, end = date(2025, 1, 1), date(2025, 1, 11)
        value, coverage = exposure(start, end, self._daily(date(2024, 1, 1), 5))
        assert value is None
        assert coverage == 0.0

    def test_empty_frame_is_none_not_zero(self):
        value, coverage = exposure(
            date(2025, 1, 1), date(2025, 1, 11), pd.DataFrame()
        )
        assert value is None
        assert coverage == 0.0

    def test_days_outside_the_window_are_excluded(self):
        start, end = date(2025, 1, 5), date(2025, 1, 8)
        daily = pd.concat(
            [self._daily(date(2025, 1, 1), 4, 100.0), self._daily(start, 3, 10.0)]
        )
        value, coverage = exposure(start, end, daily)
        assert value == pytest.approx(10.0)
        assert coverage == pytest.approx(1.0)

    def test_unknown_agg_raises(self):
        with pytest.raises(ValueError, match="unknown agg"):
            exposure(date(2025, 1, 1), date(2025, 1, 2), pd.DataFrame(), "median")
