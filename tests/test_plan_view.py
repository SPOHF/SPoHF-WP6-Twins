"""Tests for the red multi-height plan view: latest values, placement,
interpolation and the page that draws them.

The view-model is pure, so most of this needs no database; the route tests stub
the two MySQL calls the page makes, as ``test_uniformity_route`` does.
"""

import os

os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")
os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "dev")
os.environ.setdefault("WP6_OIDC_SESSION_SECRET", "dev-session-secret-dev-session-secret")
os.environ.setdefault(
    "WP6_RED_TSDB_URL", "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red",
)

import dataclasses
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wp6_data.red import deps
from wp6_data.red.db import wire_device_id, wire_readings_frame
from wp6_data.red.multi_height.plan_view import (
    MIN_SCALE_SPAN,
    colour_range,
    interpolate_field,
    latest_node_readings,
    place_nodes,
    render_plan_svg,
)
from wp6_data.red.multi_height.svg import PLAN_LAYOUT_PATH, parse_plan_layout
from wp6_data.red.routes.multi_height import MULTI_HEIGHT_VIEWS
from wp6_data.red.wires import invalidate_wire_cache

PLAN_PATH = "/multi_height/plan-view"
DAY = datetime(2026, 8, 12, 12, tzinfo=UTC)
WIRES = ["WS_01_02", "WS_01_03"]
LAYOUT = parse_plan_layout(PLAN_LAYOUT_PATH)


def _frame(temps: dict[str, list[float]], measurement="temp") -> pd.DataFrame:
    """``temps``: wire -> temperature at H1..H5; an older reading precedes each."""
    records = []
    for wire, values in temps.items():
        for h, value in enumerate(values, start=1):
            for age, v in ((1, value - 10), (0, value)):
                records.append({
                    "device": wire_device_id(wire, h), "height": h,
                    "measurement": measurement,
                    "time": DAY - timedelta(hours=age), "value": v,
                })
    return wire_readings_frame(records)


class TestLatestNodeReadings:
    def test_takes_the_most_recent_reading_per_height(self):
        out = latest_node_readings(_frame({"WS_01_02": [20, 21, 22, 23, 24]}), WIRES, "temp")

        assert [out["WS_01_02"][h].value for h in range(1, 6)] == [20, 21, 22, 23, 24]

    def test_wire_that_never_reported_is_empty_not_zero(self):
        out = latest_node_readings(_frame({"WS_01_02": [20] * 5}), WIRES, "temp")

        assert out["WS_01_03"] == {}

    def test_other_measurements_are_ignored(self):
        out = latest_node_readings(_frame({"WS_01_02": [20] * 5}, "hum"), WIRES, "temp")

        assert out["WS_01_02"] == {}


class TestPlacement:
    def test_every_wire_is_placed_even_past_the_declared_slots(self):
        wires = [f"WS_01_{i:02d}" for i in range(len(LAYOUT.slots) + 2)]
        nodes = place_nodes({w: {} for w in wires}, LAYOUT)

        assert sorted(n.wire for n in nodes) == wires


class TestInterpolation:
    def _nodes(self, temps):
        return place_nodes(latest_node_readings(_frame(temps), WIRES, "temp"), LAYOUT)

    def test_field_stays_between_the_readings(self):
        nodes = self._nodes({"WS_01_02": [20] * 5, "WS_01_03": [30] * 5})
        field = interpolate_field(nodes, 1, LAYOUT)

        assert field.min() >= 20 and field.max() <= 30

    def test_no_reading_at_height_gives_no_field(self):
        assert interpolate_field(self._nodes({}), 1, LAYOUT) is None

    def test_scale_never_collapses_to_a_hairline(self):
        lo, hi = colour_range(self._nodes({"WS_01_02": [25.0] * 5, "WS_01_03": [25.1] * 5}))

        assert hi - lo >= MIN_SCALE_SPAN


def test_svg_shows_each_wire_and_its_values():
    nodes = place_nodes(
        latest_node_readings(_frame({"WS_01_02": [20.5, 21, 22, 23, 24]}), WIRES, "temp"),
        LAYOUT,
    )
    svg = render_plan_svg(nodes, LAYOUT, 1, "°C")

    assert "WS_01_02" in svg and "WS_01_03" in svg
    assert ">20.5<" in svg
    assert "—" in svg  # WS_01_03 has nothing yet


class _StubDb:
    def __init__(self, frame):
        self._frame = frame

    async def get_active_wire_ids(self):
        return list(WIRES)

    async def get_wire_sensor_readings(self, start=None, end=None, limit=None):
        return self._frame

    async def get_wire_device_summary(self):
        return {wire_device_id(w, 1): {"readings": 1, "last_seen": DAY} for w in WIRES}


@pytest.fixture(scope="module")
def app():
    from wp6_data.shared.templates import config as tmpl_config

    saved = (
        tmpl_config._dashboard_id, tmpl_config._dashboard_title,
        tmpl_config._twin_theme_css, tmpl_config._data_sources,
    )
    from wp6_data.red.dashboard import config
    from wp6_data.shared.app_factory import create_app

    test_config = dataclasses.replace(
        config, lifespan_startup=None, lifespan_shutdown=None,
    )
    try:
        yield create_app(test_config)
    finally:
        (
            tmpl_config._dashboard_id, tmpl_config._dashboard_title,
            tmpl_config._twin_theme_css, tmpl_config._data_sources,
        ) = saved


@pytest.fixture
def client(app, monkeypatch):
    invalidate_wire_cache()
    made = []

    def _factory(frame):
        monkeypatch.setattr(deps, "db", _StubDb(frame))
        c = TestClient(app)
        c.__enter__()
        assert c.get("/auth/login", follow_redirects=False).status_code == 302
        made.append(c)
        return c

    yield _factory
    for c in made:
        c.__exit__(None, None, None)
    invalidate_wire_cache()


class TestPlanPage:
    def test_hub_offers_the_view(self, client):
        assert PLAN_PATH in {v["href"] for v in MULTI_HEIGHT_VIEWS}
        assert PLAN_PATH in client(_frame({})).get("/multi_height").text

    def test_renders_every_wire_with_latest_values(self, client):
        resp = client(_frame({
            "WS_01_02": [27.4, 26.8, 26.1, 25.3, 24.6],
            "WS_01_03": [28.1, 27.3, 26.6, 25.8, 25.0],
        })).get(PLAN_PATH)

        assert resp.status_code == 200
        for text in ("WS_01_02", "WS_01_03", "27.4", "25.0"):
            assert text in resp.text

    def test_survives_no_readings(self, client):
        resp = client(_frame({})).get(PLAN_PATH)

        assert resp.status_code == 200
        assert "No wire has reported" in resp.text

    def test_bad_height_falls_back(self, client):
        resp = client(_frame({"WS_01_02": [20] * 5})).get(PLAN_PATH, params={"height": 9})

        assert resp.status_code == 200
