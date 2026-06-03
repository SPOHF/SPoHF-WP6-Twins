"""Tests for risk-episode detection (issue 014)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from wp6_data.red.risk.episodes import detect_episodes

MIN_DURATION = timedelta(minutes=30)


_BASE = pd.Timestamp("2026-05-26T12:00:00", tz="UTC")


def _df(rows):
    """rows: list of (minute_offset, value, active) from 2026-05-26T12:00 UTC."""
    return pd.DataFrame({
        "time": [_BASE + pd.Timedelta(minutes=m) for m, _, _ in rows],
        "value": [v for _, v, _ in rows],
        "active": [a for _, _, a in rows],
    })


def test_closed_episode_records_start_end_and_peak():
    df = _df([(0, 1.0, True), (15, 3.0, True), (30, 2.0, True), (45, 0.0, False)])
    eps = detect_episodes(df, MIN_DURATION)
    assert len(eps) == 1
    ep = eps[0]
    assert ep.start == pd.Timestamp("2026-05-26T12:00:00", tz="UTC")
    assert ep.end == pd.Timestamp("2026-05-26T12:45:00", tz="UTC")  # resolution time
    assert ep.peak == 3.0


def test_short_span_is_suppressed_as_flapping():
    df = _df([(0, 5.0, True), (15, 0.0, False)])  # 15 min < 30 min
    assert detect_episodes(df, MIN_DURATION) == []


def test_open_episode_has_no_end():
    df = _df([(0, 1.0, True), (15, 2.0, True), (30, 4.0, True)])  # active at end
    eps = detect_episodes(df, MIN_DURATION)
    assert len(eps) == 1
    assert eps[0].end is None
    assert eps[0].peak == 4.0


def test_multiple_spans_yield_multiple_episodes():
    df = _df([
        (0, 1.0, True), (15, 1.0, True), (30, 0.0, False),
        (45, 1.0, True), (60, 1.0, True), (75, 0.0, False),
    ])
    assert len(detect_episodes(df, MIN_DURATION)) == 2


def test_empty_frame_yields_no_episodes():
    assert detect_episodes(pd.DataFrame(columns=["time", "value", "active"]), MIN_DURATION) == []
