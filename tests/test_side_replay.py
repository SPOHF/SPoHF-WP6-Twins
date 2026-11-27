"""Pure tests for the side-section replay: window rules, step choice, frames."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from wp6_data.red.db import wire_device_id, wire_readings_frame
from wp6_data.red.multi_height.side_replay import (
    MAX_FRAMES,
    MAX_WINDOW,
    build_frames,
    choose_step,
    frame_index_at,
    frame_times,
    resolve_window,
    shared_scale,
    stale_after,
)
from wp6_data.red.multi_height.side_section import (
    MEASUREMENT_STYLES,
    PlacedNode,
    colour_range,
    place_nodes,
    usable,
)
from wp6_data.red.multi_height.svg import SECTION_LAYOUT_PATH, parse_section_layout

T0 = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)
WIRES = ["WS_01_02", "WS_01_03"]
STYLE = MEASUREMENT_STYLES["temp"]


def _readings(rows: list[tuple[str, int, int, float]], measurement="temp"):
    """rows: (wire, height, minutes after T0, value)."""
    return wire_readings_frame([
        {
            "device": wire_device_id(w, h), "height": h, "measurement": measurement,
            "time": T0 + timedelta(minutes=m), "value": v,
        }
        for w, h, m, v in rows
    ])


class TestWindow:
    def test_defaults_end_to_latest(self):
        latest = T0 + timedelta(hours=5)
        assert resolve_window(T0, None, latest) == (T0, latest)

    def test_missing_start_or_inverted_window_falls_back_to_latest_view(self):
        assert resolve_window(None, T0, T0) is None
        assert resolve_window(T0, T0 - timedelta(hours=1), T0) is None
        assert resolve_window(T0, None, None) is None

    def test_long_window_keeps_its_end_and_is_capped(self):
        end = T0 + timedelta(days=60)
        start, got_end = resolve_window(T0, end, None)

        assert got_end == end
        assert end - start == MAX_WINDOW


class TestStep:
    def test_short_window_uses_the_finest_step(self):
        assert choose_step(timedelta(hours=3)) == timedelta(minutes=15)

    def test_frame_count_stays_capped_however_long_the_window(self):
        for span in (timedelta(hours=30), timedelta(days=3), MAX_WINDOW):
            step = choose_step(span)
            assert len(frame_times(T0, T0 + span, step)) <= MAX_FRAMES + 1

    def test_last_frame_is_always_the_window_end(self):
        end = T0 + timedelta(minutes=40)
        times = frame_times(T0, end, timedelta(minutes=15))

        assert times[0] == pd.Timestamp(T0)
        assert times[-1] == pd.Timestamp(end)


class TestBuildFrames:
    def _frames(self, rows, minutes=(0, 30, 60), stale=timedelta(minutes=45)):
        times = [pd.Timestamp(T0 + timedelta(minutes=m)) for m in minutes]
        return build_frames(_readings(rows), WIRES, "temp", times, stale)

    def test_each_frame_takes_the_last_reading_at_or_before_it(self):
        frames = self._frames([("WS_01_02", 1, 0, 20), ("WS_01_02", 1, 20, 21),
                               ("WS_01_02", 1, 50, 22)])

        assert [f.readings["WS_01_02"][1].value for f in frames] == [20, 21, 22]

    def test_nothing_before_a_frame_means_absent_not_zero(self):
        frames = self._frames([("WS_01_02", 1, 20, 21)])

        assert frames[0].readings["WS_01_02"] == {}
        assert frames[1].readings["WS_01_02"][1].value == 21

    def test_reading_past_the_threshold_is_stale_but_kept(self):
        frames = self._frames([("WS_01_02", 1, 0, 20)])

        fresh, _, old = (f.readings["WS_01_02"][1] for f in frames)
        assert not fresh.stale and old.stale
        assert old.value == 20  # shown greyed, not dropped

    def test_stale_readings_do_not_feed_the_interpolation_or_the_scale(self):
        frames = self._frames([("WS_01_02", 1, 0, 20), ("WS_01_03", 1, 55, 30)])
        last = frames[-1].readings

        assert not usable(last["WS_01_02"][1], STYLE)
        assert usable(last["WS_01_03"][1], STYLE)
        nodes = place_nodes(last, parse_section_layout(SECTION_LAYOUT_PATH))
        lo, hi = colour_range(nodes, STYLE)
        assert lo > 20  # the stale 20 is not in the range

    def test_other_measurements_and_wires_are_ignored(self):
        df = _readings([("WS_09_09", 1, 0, 5)])
        out = build_frames(df, WIRES, "temp", [pd.Timestamp(T0)], timedelta(hours=1))

        assert out[0].readings == {w: {} for w in WIRES}
        assert build_frames(df, WIRES, "hum", [pd.Timestamp(T0)], timedelta(hours=1))[0].readings[
            "WS_01_02"] == {}

    def test_stale_threshold_is_two_steps_and_at_least_an_hour(self):
        assert stale_after(timedelta(minutes=15)) == timedelta(hours=1)
        assert stale_after(timedelta(hours=6)) == timedelta(hours=12)


def test_one_scale_spans_every_frame():
    layout = parse_section_layout(SECTION_LAYOUT_PATH)
    times = [pd.Timestamp(T0 + timedelta(minutes=m)) for m in (0, 30)]
    frames = build_frames(
        _readings([("WS_01_02", 1, 0, 10), ("WS_01_02", 1, 30, 40)]),
        WIRES, "temp", times, timedelta(hours=1),
    )
    placed: list[list[PlacedNode]] = [place_nodes(f.readings, layout) for f in frames]

    lo, hi = shared_scale(placed, STYLE)
    assert lo <= 10 and hi >= 40
    assert colour_range(placed[0], STYLE) != (lo, hi)


def test_frame_index_picks_the_nearest_frame_and_defaults_to_the_first():
    times = [pd.Timestamp(T0 + timedelta(minutes=m)) for m in (0, 15, 30)]

    assert frame_index_at(times, None) == 0
    assert frame_index_at(times, T0 + timedelta(minutes=26)) == 2
