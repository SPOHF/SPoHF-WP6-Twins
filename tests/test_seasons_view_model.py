"""Tests for the pure half of blue's seasons view model.

Blue's lane axis is the treatment, and every treatment spans the same season, so
the things worth pinning are attachment (which season a measurement belongs to)
and summarisation (how a season's many samples become one figure).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from wp6_data.blue.seasons.config import SeasonConfig
from wp6_data.blue.seasons.view_model import build_seasons

SEASONS = [
    SeasonConfig(label="2024 season", start=date(2024, 3, 1), end=date(2024, 11, 1)),
    SeasonConfig(label="2025 season", start=date(2025, 3, 1), end=date(2025, 11, 1)),
]
TREATMENTS = {"Std": "Std", "Org1": "Org1", "Ca": "Ca"}


def _obs(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "device", "value"])


def _weather(start: date, days: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(days)],
            "value": [18.0] * days,
        }
    )


def _full_weather() -> pd.DataFrame:
    first, last = SEASONS[0].start, SEASONS[-1].end
    return _weather(first, (last - first).days)


class TestLanes:
    def test_a_lane_per_season_per_treatment(self):
        view = build_seasons(SEASONS, TREATMENTS, _obs([]), _full_weather())
        assert len(view.lanes) == len(SEASONS) * len(TREATMENTS)

    def test_an_unsampled_treatment_still_gets_a_lane(self):
        """An absent plot is a fact about the season, not a row to omit."""
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2025, 7, 10), "Std", 12.0)]), _full_weather(),
        )
        assert len(view.measured) == 1
        assert len(view.lanes) == len(SEASONS) * len(TREATMENTS)

    def test_lane_group_is_the_season_label(self):
        view = build_seasons(SEASONS, TREATMENTS, _obs([]), _full_weather())
        assert {lane.group for lane in view.lanes} == {s.label for s in SEASONS}

    def test_lanes_span_their_whole_season(self):
        """Nothing staggers: every lane in a season shares one span."""
        view = build_seasons(SEASONS, TREATMENTS, _obs([]), _full_weather())
        spans = {(lane.group, lane.cohort.start, lane.cohort.end) for lane in view.lanes}
        assert len(spans) == len(SEASONS)

    def test_treatment_order_is_preserved(self):
        view = build_seasons(SEASONS, TREATMENTS, _obs([]), _full_weather())
        first_season = [lane for lane in view.lanes if lane.group == SEASONS[0].label]
        assert [lane.cohort.label for lane in first_season] == list(TREATMENTS.values())


class TestAttachment:
    def test_a_measurement_lands_in_the_season_containing_it(self):
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2024, 7, 16), "Std", 10.1)]), _full_weather(),
        )
        assert view.measured[0].group == "2024 season"
        assert view.measured[0].cohort.label == "Std"

    def test_a_measurement_outside_every_season_is_reported_not_dropped(self):
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2025, 1, 5), "Std", 9.9)]), _full_weather(),
        )
        assert not view.measured
        assert [u.day for u in view.unattached] == [date(2025, 1, 5)]

    def test_an_undeclared_treatment_is_reported_not_dropped(self):
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2025, 7, 10), "mystery", 9.9)]), _full_weather(),
        )
        assert not view.measured
        assert [u.device for u in view.unattached] == ["mystery"]


class TestSummarising:
    def test_a_seasons_samples_become_one_figure(self):
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2025, 7, 10), "Std", 12.0),
                  (date(2025, 7, 18), "Std", 14.0),
                  (date(2025, 8, 1), "Std", 13.0)]),
            _full_weather(),
        )
        markers = view.measured[0].markers
        assert len(markers) == 1
        assert markers[0].value == 13.0
        assert markers[0].samples == 3

    def test_a_total_measure_sums_across_the_harvest_passes(self):
        """A yield picked across several passes is a total, not a per-pass mean."""
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2025, 7, 9), "Std", 100.0),
                  (date(2025, 7, 18), "Std", 60.0)]),
            _full_weather(), measure_agg="sum",
        )
        assert view.measured[0].markers[0].value == 160.0

    def test_seasons_are_summarised_separately(self):
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2024, 7, 16), "Std", 10.0),
                  (date(2025, 7, 10), "Std", 13.0)]),
            _full_weather(),
        )
        by_group = {lane.group: lane.markers[0].value for lane in view.measured}
        assert by_group == {"2024 season": 10.0, "2025 season": 13.0}

    def test_two_level_takes_the_mean_per_pick_then_sums_the_picks(self):
        """A season yield is neither the flat mean nor the flat sum."""
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([  # two plants on each of two picks
                (date(2025, 7, 9), "Std", 100.0), (date(2025, 7, 9), "Std", 200.0),
                (date(2025, 7, 18), "Std", 300.0), (date(2025, 7, 18), "Std", 500.0),
            ]),
            _full_weather(), measure_agg="avg", measure_period_agg="sum",
        )
        marker = view.measured[0].markers[0]
        # mean(100, 200) + mean(300, 500) = 150 + 400
        assert marker.value == 550.0
        # ...and neither of the one-level answers
        assert marker.value != round(sum([100, 200, 300, 500]) / 4, 2)
        assert marker.value != float(sum([100, 200, 300, 500]))
        assert marker.samples == 4

    def test_two_level_hover_names_both_levels(self):
        view = build_seasons(
            SEASONS, TREATMENTS,
            _obs([(date(2025, 7, 9), "Std", 100.0),
                  (date(2025, 7, 18), "Std", 300.0)]),
            _full_weather(), measure_agg="avg", measure_period_agg="sum",
        )
        detail = view.measured[0].markers[0].detail
        assert "sum of 2 picks" in detail
        assert "mean of 2 samples" in detail

    def test_no_period_agg_keeps_the_flat_behaviour(self):
        """Measures that declare one level must not shift underfoot."""
        rows = [(date(2025, 7, 9), "Std", 100.0), (date(2025, 7, 9), "Std", 200.0),
                (date(2025, 7, 18), "Std", 300.0)]
        view = build_seasons(
            SEASONS, TREATMENTS, _obs(rows), _full_weather(), measure_agg="avg",
        )
        assert view.measured[0].markers[0].value == 200.0  # mean of all three

    def test_an_unknown_period_agg_raises_rather_than_guessing(self):
        with pytest.raises(ValueError, match="unknown measure period agg"):
            build_seasons(
                SEASONS, TREATMENTS, _obs([]), _full_weather(),
                measure_period_agg="median",
            )

    def test_an_unknown_measure_agg_raises_rather_than_guessing(self):
        with pytest.raises(ValueError, match="unknown measure agg"):
            build_seasons(
                SEASONS, TREATMENTS, _obs([]), _full_weather(), measure_agg="median",
            )


class TestCoverage:
    def test_full_weather_leaves_every_lane_covered(self):
        view = build_seasons(SEASONS, TREATMENTS, _obs([]), _full_weather())
        assert not view.partial

    def test_absent_weather_gives_zero_coverage(self):
        view = build_seasons(
            SEASONS, TREATMENTS, _obs([]), pd.DataFrame(columns=["date", "value"]),
        )
        assert len(view.partial) == len(view.lanes)
        assert all(lane.coverage == 0.0 for lane in view.lanes)
