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
    MEASUREMENT_STYLES,
    colour_range,
    interpolate_field,
    interpolate_section,
    latest_node_readings,
    place_nodes,
    render_plan_svg,
    render_side_svg,
)
from wp6_data.red.multi_height.svg import PLAN_LAYOUT_PATH, parse_plan_layout
from wp6_data.red.routes.multi_height import MULTI_HEIGHT_VIEWS
from wp6_data.red.wires import invalidate_wire_cache

PLAN_PATH = "/multi_height/plan-view"
SIDE_PATH = "/multi_height/side-section"
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
        style = MEASUREMENT_STYLES["temp"]
        lo, hi = colour_range(
            self._nodes({"WS_01_02": [25.0] * 5, "WS_01_03": [25.1] * 5}), style,
        )

        assert hi - lo >= style.min_span

    def test_section_stays_between_the_readings_and_runs_down_the_heights(self):
        nodes = self._nodes({
            "WS_01_02": [20, 21, 22, 23, 24], "WS_01_03": [30, 31, 32, 33, 34],
        })
        field = interpolate_section(nodes, LAYOUT)

        assert field.min() >= 20 and field.max() <= 34
        assert field[0, 0] < field[-1, 0]  # H1 (top) is cooler than H5 here
        assert field[0, 0] < field[0, -1]  # first wire is cooler than the last

    def test_section_without_readings_has_no_field(self):
        assert interpolate_section(self._nodes({}), LAYOUT) is None


def test_nodes_share_one_line():
    nodes = place_nodes({f"WS_01_{i:02d}": {} for i in range(len(LAYOUT.slots) + 2)}, LAYOUT)

    assert len({n.y for n in nodes}) == 1


def test_nodes_are_spread_evenly_across_the_rectangle():
    nodes = place_nodes({f"WS_01_{i:02d}": {} for i in range(3)}, LAYOUT)
    gaps = {round(b.x - a.x, 6) for a, b in zip(nodes, nodes[1:], strict=False)}
    area = LAYOUT.area

    assert len(gaps) == 1
    assert nodes[0].x - area["x"] == pytest.approx(area["x"] + area["width"] - nodes[-1].x)


class TestDeadSensors:
    def _nodes(self, temps):
        return place_nodes(latest_node_readings(_frame(temps), WIRES, "temp"), LAYOUT)

    def test_zero_is_shown_but_not_interpolated(self):
        nodes = self._nodes({"WS_01_02": [0, 20, 20, 20, 20], "WS_01_03": [30] * 5})
        field = interpolate_field(nodes, 1, LAYOUT)

        assert field.min() == 30  # the dead H1 sensor does not pull toward 0
        assert ">0.0<" in render_plan_svg(nodes, LAYOUT, 1, "temp", "Temperature", "°C")
        assert colour_range(nodes, MEASUREMENT_STYLES["temp"])[0] > 15

    def test_section_bridges_a_dead_height(self):
        nodes = self._nodes({"WS_01_02": [20, 0, 30, 40, 50], "WS_01_03": [20, 0, 30, 40, 50]})
        field = interpolate_section(nodes, LAYOUT)

        assert field.min() >= 20

    def test_all_dead_gives_no_field(self):
        nodes = self._nodes({"WS_01_02": [0] * 5})

        assert interpolate_field(nodes, 1, LAYOUT) is None
        assert interpolate_section(nodes, LAYOUT) is None

    def test_each_height_has_its_own_field(self):
        nodes = self._nodes({"WS_01_02": [10, 20, 20, 20, 20], "WS_01_03": [12, 30, 30, 30, 30]})

        assert interpolate_field(nodes, 1, LAYOUT).max() <= 12
        assert interpolate_field(nodes, 2, LAYOUT).min() >= 20


def test_svg_shows_each_wire_and_its_values():
    nodes = place_nodes(
        latest_node_readings(_frame({"WS_01_02": [20.5, 21, 22, 23, 24]}), WIRES, "temp"),
        LAYOUT,
    )
    svg = render_plan_svg(nodes, LAYOUT, 1, "temp", "Temperature", "°C")

    assert "WS_01_02" in svg and "WS_01_03" in svg
    assert ">20.5<" in svg
    assert "—" in svg  # WS_01_03 has nothing yet


def test_side_svg_shows_each_wire_and_its_values():
    nodes = place_nodes(
        latest_node_readings(_frame({"WS_01_02": [20.5, 21, 22, 23, 24]}), WIRES, "temp"),
        LAYOUT,
    )
    svg = render_side_svg(nodes, LAYOUT, "temp", "Temperature", "°C")

    assert "WS_01_02" in svg and ">20.5<" in svg and ">H5<" in svg


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


class TestSideSectionPage:
    def test_card_is_second_after_the_simple_view_with_the_requested_text(self):
        hrefs = [v["href"] for v in MULTI_HEIGHT_VIEWS]

        assert hrefs[:2] == ["/multi_height/single-simple", SIDE_PATH]
        by_href = {v["href"]: v for v in MULTI_HEIGHT_VIEWS}
        assert by_href[PLAN_PATH]["description"].startswith("Visualization: above view.")
        assert by_href[SIDE_PATH]["description"].startswith("Visualization: side view.")

    @pytest.mark.parametrize("path", [PLAN_PATH, SIDE_PATH])
    @pytest.mark.parametrize(
        ("measurement", "label", "value"),
        [("par", "PAR", ">310<"), ("hum", "Humidity", ">61.5<"), ("co2", "CO₂", ">805<")],
    )
    def test_each_measurement_renders_with_a_selector(
        self, client, path, measurement, label, value,
    ):
        nums = {"par": 310, "hum": 61.5, "co2": 805}[measurement]
        resp = client(_frame({"WS_01_02": [nums] * 5}, measurement)).get(
            path, params={"measurement": measurement},
        )

        assert resp.status_code == 200
        assert value in resp.text and label in resp.text
        assert "measurement=co2" in resp.text  # the radio pills

    def test_bad_measurement_falls_back_and_empty_names_it(self, client):
        resp = client(_frame({})).get(SIDE_PATH, params={"measurement": "x"})

        assert resp.status_code == 200
        assert "No wire has reported temperature" in resp.text
