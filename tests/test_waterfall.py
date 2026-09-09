"""Tests for the twin-agnostic waterfall chart.

Like the cycles model, this must stay free of any twin's domain language, so the
fixtures use neutral names.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from wp6_data.shared.cycles import CohortSpec, CycleSpec, generate_cohorts
from wp6_data.shared.waterfall import (
    LANE_COLOR,
    VALUE_COLORS,
    VALUE_SCALE,
    Lane,
    Marker,
    render_waterfall,
    series_colors,
    value_color,
    value_range,
)

SPEC = CohortSpec(interval=timedelta(days=7), duration=timedelta(weeks=8))
CYCLE = CycleSpec("cycle one", date(2025, 6, 16), date(2025, 10, 6))
# Distinctive to a real projection trace; "heatmap" alone also appears in the
# Plotly template that ships inside every figure's JSON.
PROJECTION_HOVER = "%{x|%d %b %Y}"


def _lanes(n: int = 4) -> list[Lane]:
    return [Lane(cohort=c) for c in generate_cohorts(CYCLE, SPEC)[:n]]


def _annotations(html: str) -> list[dict]:
    """The figure's layout annotations — the value chips live here, not in a trace.

    Asserting on the rendered JSON rather than on substrings matters for
    placement: every date in the span appears in the projection's x array, so
    "is this date in the HTML" would pass whatever the chip was anchored to.
    """
    i = html.index("Plotly.newPlot")
    start = html.index("[", i)
    depth, j = 0, start
    while True:
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
        if depth == 0:
            break
        j += 1
    layout_start = html.index("{", j)
    depth, k = 0, layout_start
    while True:
        if html[k] == "{":
            depth += 1
        elif html[k] == "}":
            depth -= 1
        if depth == 0:
            break
        k += 1
    return json.loads(html[layout_start:k + 1]).get("annotations", [])


def _daily() -> pd.DataFrame:
    days = (CYCLE.end - CYCLE.start).days
    return pd.DataFrame(
        {
            "date": [CYCLE.start + timedelta(days=i) for i in range(days)],
            "value": [20.0 + (i % 7) for i in range(days)],
        }
    )


class TestRenderWaterfall:
    def test_no_lanes_returns_none(self):
        assert render_waterfall([]) is None

    def test_every_lane_is_labelled(self):
        lanes = _lanes()
        html = render_waterfall(lanes)
        assert html is not None
        for lane in lanes:
            # Plotly JSON-escapes non-ASCII, so match the ASCII head of the label.
            assert lane.cohort.label.split(" \u00b7 ")[0] in html

    def test_bars_render_without_a_daily_series(self):
        """No series to project means plain bars, not a missing chart."""
        html = render_waterfall(_lanes())
        assert html is not None
        assert LANE_COLOR in html

    def test_the_daily_series_is_projected_onto_the_bars(self):
        html = render_waterfall(_lanes(), _daily())
        assert "heatmap" in html
        assert PROJECTION_HOVER in html

    def test_a_day_outside_every_cohort_is_not_projected(self):
        """The series is drawn where it acted on a cohort, nowhere else."""
        lanes = _lanes(1)
        daily = _daily()
        marker = -999.0
        # A day after the only lane ends: in the frame, but on no bar.
        daily.loc[daily["date"] == lanes[0].cohort.end, "value"] = marker
        html = render_waterfall(lanes, daily)
        assert str(marker) not in html

    def test_an_unsampled_lane_carries_no_value_chip(self):
        html = render_waterfall(_lanes(), _daily())
        assert "bordercolor" not in html

    def test_a_value_is_anchored_to_its_cohorts_harvest_end(self):
        """An outcome is observed when the cohort completes, not part-way."""
        lanes = _lanes(1)
        cohort = lanes[0].cohort
        lanes[0] = Lane(cohort=cohort, markers=[Marker(3.9, "Brix-ish")])
        chips = [a for a in _annotations(render_waterfall(lanes, _daily()))
                 if a.get("text") == "3.9"]
        assert len(chips) == 1
        assert chips[0]["x"] == cohort.end.isoformat()
        assert chips[0]["xanchor"] == "right"

    def test_chips_sharing_a_harvest_end_step_apart(self):
        lanes = _lanes(1)
        lanes[0] = Lane(
            cohort=lanes[0].cohort,
            markers=[Marker(3.9, series="Alpha"), Marker(4.1, series="Beta")],
        )
        chips = [a for a in _annotations(render_waterfall(lanes, _daily()))
                 if a.get("text") in {"3.9", "4.1"}]
        assert len(chips) == 2
        assert {c["x"] for c in chips} == {lanes[0].cohort.end.isoformat()}
        # Same date, different pixel offsets, so they cannot overprint.
        assert len({c["xshift"] for c in chips}) == 2

    def test_chip_fill_tracks_the_value_relative_to_the_others(self):
        lanes = _lanes(3)
        for i, value in enumerate((1.0, 5.0, 9.0)):
            lanes[i] = Lane(cohort=lanes[i].cohort, markers=[Marker(value)])
        chips = {a["text"]: a for a in _annotations(render_waterfall(lanes, _daily()))
                 if a.get("text") in {"1", "5", "9"}}
        assert len(chips) == 3
        # Lowest takes the pale end, highest the deep end, and no two agree.
        assert chips["1"]["bgcolor"] == VALUE_SCALE[0]
        assert chips["9"]["bgcolor"] == VALUE_SCALE[-1]
        assert len({c["bgcolor"] for c in chips.values()}) == 3

    def test_the_outline_still_says_which_series(self):
        """Fill carries the value, so identity moves to the chip's border."""
        lanes = _lanes(1)
        lanes[0] = Lane(
            cohort=lanes[0].cohort,
            markers=[Marker(3.9, series="Alpha"), Marker(4.1, series="Beta")],
        )
        chips = [a for a in _annotations(render_waterfall(lanes, _daily()))
                 if a.get("text") in {"3.9", "4.1"}]
        assert {c["bordercolor"] for c in chips} == {
            VALUE_COLORS[0], VALUE_COLORS[1]
        }

    def test_series_colors_match_what_was_drawn(self):
        lanes = _lanes(1)
        lanes[0] = Lane(
            cohort=lanes[0].cohort,
            markers=[Marker(3.9, series="Alpha"), Marker(4.1, series="Beta")],
        )
        colors = series_colors(lanes)
        assert colors == {"Alpha": VALUE_COLORS[0], "Beta": VALUE_COLORS[1]}
        html = render_waterfall(lanes, _daily())
        borders = {a.get("bordercolor") for a in _annotations(html)}
        assert set(colors.values()) <= borders

    def test_coverage_is_shown_by_gaps_not_by_fading(self):
        """A dimmed bar would corrupt a value encoded as colour."""
        lanes = _lanes(2)
        lanes[0] = Lane(cohort=lanes[0].cohort, coverage=0.5)
        html = render_waterfall(lanes, _daily())
        assert "opacity" not in html

    def test_paired_series_are_separate_named_traces(self):
        lanes = _lanes(2)
        lanes[0] = Lane(
            cohort=lanes[0].cohort,
            markers=[Marker(3.9, series="Alpha"), Marker(4.1, series="Beta")],
        )
        html = render_waterfall(lanes)
        assert "Alpha" in html
        assert "Beta" in html
        assert "3.9" in html
        assert "4.1" in html
        # Two values share one bar, so colour is what tells them apart.
        assert VALUE_COLORS[0] in html
        assert VALUE_COLORS[1] in html

    def test_groups_are_labelled_in_the_margin(self):
        cohorts = generate_cohorts(CYCLE, SPEC)[:4]
        lanes = [
            Lane(cohort=c, group="Group A" if i < 2 else "Group B")
            for i, c in enumerate(cohorts)
        ]
        html = render_waterfall(lanes)
        assert "Group A" in html
        assert "Group B" in html

    def test_projection_is_rendered_and_labelled(self):
        html = render_waterfall(_lanes(), _daily(), series_label="Mean thing")
        assert PROJECTION_HOVER in html
        assert "Mean thing" in html

    def test_renders_without_a_daily_series(self):
        html = render_waterfall(_lanes(), None, series_label="Mean thing")
        assert html is not None
        assert PROJECTION_HOVER not in html
        assert "Mean thing" not in html


class TestHowTheValueWasReached:
    """A summarised figure and a single reading must not look alike on hover."""

    def test_hover_carries_the_callers_own_phrasing(self):
        lanes = _lanes(1)
        lanes[0] = Lane(
            cohort=lanes[0].cohort,
            markers=[Marker(4.2, "Brix", detail="sum of 3 picks, 135 samples")],
        )
        chips = [a for a in _annotations(render_waterfall(lanes, _daily()))
                 if a.get("text") == "4.2"]
        assert "sum of 3 picks, 135 samples" in chips[0]["hovertext"]

    def test_a_lone_reading_says_nothing_extra(self):
        lanes = _lanes(1)
        lanes[0] = Lane(cohort=lanes[0].cohort, markers=[Marker(4.2, "Brix")])
        chips = [a for a in _annotations(render_waterfall(lanes, _daily()))
                 if a.get("text") == "4.2"]
        assert chips[0]["hovertext"].endswith("4.2")


class TestValueScale:
    def test_range_spans_every_series(self):
        """One measurement of one thing gets one scale, whoever grew it."""
        lanes = _lanes(2)
        lanes[0] = Lane(cohort=lanes[0].cohort, markers=[Marker(2.0, series="A")])
        lanes[1] = Lane(cohort=lanes[1].cohort, markers=[Marker(8.0, series="B")])
        assert value_range(lanes) == (2.0, 8.0)

    def test_range_is_none_when_nothing_was_measured(self):
        assert value_range(_lanes(3)) is None

    def test_ends_of_the_range_take_the_ends_of_the_scale(self):
        assert value_color(2.0, (2.0, 8.0)) == VALUE_SCALE[0]
        assert value_color(8.0, (2.0, 8.0)) == VALUE_SCALE[-1]

    def test_a_lone_value_sits_mid_scale_rather_than_at_an_extreme(self):
        """A single reading has no relative position; implying "highest" lies."""
        assert value_color(5.0, (5.0, 5.0)) == VALUE_SCALE[len(VALUE_SCALE) // 2]

    def test_colour_rises_monotonically_with_value(self):
        span = (0.0, 10.0)
        seen = [value_color(v, span) for v in range(11)]
        assert len(set(seen)) > 1
        assert seen[0] == VALUE_SCALE[0]
        assert seen[-1] == VALUE_SCALE[-1]
