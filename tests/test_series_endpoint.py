"""End-to-end contract test for GET /api/series aggregation.

Runs against the grey twin (synthetic, no database) so it exercises the
real endpoint -> provider -> shared bucket_and_aggregate -> serialization
chain without infra. dev-auth env is set before the app imports.
"""

import os

os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")
os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "dev")
os.environ.setdefault("WP6_OIDC_SESSION_SECRET", "dev-session-secret-dev-session-secret")

import pytest
from fastapi.testclient import TestClient

BASE = "/api/series?device=herb-box-01&sensor=temp"


@pytest.fixture(scope="module")
def client():
    # Importing grey.dashboard runs create_app -> configure_dashboard, which
    # mutates module globals in shared.templates.config (dashboard identity).
    # Snapshot them first and restore on teardown so this module can't pollute
    # others (e.g. test_templates asserts the configured identity).
    from wp6_data.shared.templates import config as tmpl_config

    saved = (
        tmpl_config._dashboard_id,
        tmpl_config._dashboard_title,
        tmpl_config._twin_theme_css,
        tmpl_config._data_sources,
    )
    from wp6_data.grey.dashboard import app

    try:
        with TestClient(app) as c:
            yield c
    finally:
        (
            tmpl_config._dashboard_id,
            tmpl_config._dashboard_title,
            tmpl_config._twin_theme_css,
            tmpl_config._data_sources,
        ) = saved


def test_raw_response_unchanged_no_count(client):
    resp = client.get(BASE).json()
    assert resp["data"]
    assert "count" not in resp["data"][0]
    assert "min" not in resp["data"][0]  # range-band extremes are bucketed-only
    assert "max" not in resp["data"][0]
    assert "limit" in resp  # consistent on the non-empty path


def test_aggregation_reduces_points_and_adds_count(client):
    raw = client.get(BASE).json()
    day = client.get(BASE + "&bkt=1440&agg=avg").json()
    assert len(day["data"]) < len(raw["data"])
    assert day["truncated"] is False
    assert all("count" in d for d in day["data"])
    assert all(d["count"] >= 1 for d in day["data"])


def test_aggregation_includes_range_band_extremes(client):
    # Each bucketed point carries raw min/max for the chart's range band,
    # and they bound the aggregated line value (min <= avg <= max).
    day = client.get(BASE + "&bkt=1440&agg=avg").json()["data"]
    assert all("min" in d and "max" in d for d in day)
    assert all(d["min"] <= d["value"] <= d["max"] for d in day)


def test_day_bucket_aligns_to_local_midnight(client):
    day = client.get(BASE + "&bkt=1440&agg=avg").json()
    # display tz is whole-hour offset → naive local ISO ends at midnight.
    assert day["data"][0]["time"].endswith("T00:00:00.000000")


def test_finer_bucket_yields_more_points(client):
    day = client.get(BASE + "&bkt=1440&agg=avg").json()
    hour = client.get(BASE + "&bkt=60&agg=max").json()
    assert len(hour["data"]) > len(day["data"])


def test_invalid_agg_rejected(client):
    resp = client.get(BASE + "&bkt=60&agg=median")
    assert resp.status_code == 400
    assert "Invalid agg" in resp.json()["error"]


def test_bkt_without_agg_falls_back_to_raw(client):
    raw = client.get(BASE).json()
    bkt_only = client.get(BASE + "&bkt=1440").json()
    assert len(bkt_only["data"]) == len(raw["data"])
    assert "count" not in bkt_only["data"][0]
