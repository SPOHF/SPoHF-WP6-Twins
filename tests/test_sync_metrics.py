"""Unit tests for the shared /metrics renderer (Prometheus text format)."""

from datetime import UTC, datetime, timedelta

import pytest

from wp6_data.shared.routes.metrics import render_metrics
from wp6_data.shared.routes.status import SYNC_STATES, classify_sync

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
BUDGET = (2.0, 6.0)


def _row(**over):
    base = {
        "endpoint": "some-feed",
        "source_type": "synced",
        "last_run_at": NOW - timedelta(minutes=3),
        "last_run_success": True,
        "last_data_timestamp": NOW - timedelta(minutes=8),
        "freshness_budget": BUDGET,
        "records": 42,
        "total_runs": 10,
        "total_failures": 1,
        "consecutive_failures": 0,
    }
    base.update(over)
    return base


def _samples(text: str) -> dict[str, float]:
    """Sample lines → {'name{labels}': value}, comments dropped."""
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            key, value = line.rsplit(" ", 1)
            out[key] = float(value)
    return out


def _state_series(text: str) -> dict[str, float]:
    return {
        k.split('state="')[1].rstrip('"}'): v
        for k, v in _samples(text).items()
        if k.startswith("wp6_sync_state{")
    }


def test_unreadable_metadata_reports_down_as_a_real_sample():
    # The old fallback was "# wp6_sync_up 0" — a comment, which Prometheus ignores.
    assert _samples(render_metrics("t", None, NOW)) == {'wp6_sync_up{twin="t"}': 0}


def test_readable_metadata_reports_up():
    assert _samples(render_metrics("t", [], NOW))['wp6_sync_up{twin="t"}'] == 1


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"last_data_timestamp": NOW - timedelta(hours=(BUDGET[0] + BUDGET[1]) / 2)},
        {"last_data_timestamp": NOW - timedelta(hours=BUDGET[1] + 1)},
        {"last_run_success": False},
        {"last_run_at": None},
        {"source_type": "manual", "freshness_budget": None},
    ],
)
def test_state_is_one_hot_and_matches_the_status_page(over):
    row = _row(**over)
    states = _state_series(render_metrics("t", [row], NOW))

    assert set(states) == set(SYNC_STATES)
    assert [s for s, v in states.items() if v == 1] == [classify_sync(row, NOW)[0]]


def test_series_carry_twin_endpoint_and_source_type():
    text = render_metrics("t", [_row(consecutive_failures=3)], NOW)
    key = 'wp6_sync_consecutive_failures{twin="t",endpoint="some-feed",source_type="synced"}'
    assert _samples(text)[key] == 3


def test_lag_is_seconds_since_last_data_point():
    lag = timedelta(minutes=8)
    text = render_metrics("t", [_row(last_data_timestamp=NOW - lag)], NOW)
    key = 'wp6_sync_data_lag_seconds{twin="t",endpoint="some-feed",source_type="synced"}'
    assert _samples(text)[key] == lag.total_seconds()
