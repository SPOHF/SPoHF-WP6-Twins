"""Route-level tests for the red "Uniformity across wires" page.

The page reads MySQL and nothing else — no TSDB pool, because it renders live
readings rather than the persisted risk log — so a stub database is the whole
fixture. What is pinned here is the page's contract with the reader: it never
asks which wire, it survives a day the wires were silent, and the selection made
by one control is not thrown away by the other.
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
from wp6_data.red.multi_height.config import CROP_METRICS, load_uniformity_config
from wp6_data.red.routes.multi_height import (
    DEFAULT_UNIFORMITY_METRIC,
    MULTI_HEIGHT_VIEWS,
)
from wp6_data.red.wires import wire_ids

UNIFORMITY_PATH = "/multi_height/uniformity"
DAY = datetime(2026, 8, 12, tzinfo=UTC)
CONFIG = load_uniformity_config(deps._METADATA_PATH)
# Well past the configured minimum, so a fixture wire is always comparable.
HOURS = int(CONFIG.min_coverage_hours) + 6


class _StubDb:
    """Serves a fixed readings frame; the page needs no other database call."""

    def __init__(self, frame: pd.DataFrame, last_seen=DAY):
        self._frame = frame
        self._last_seen = last_seen

    async def get_wire_sensor_readings(self, start=None, end=None, limit=None):
        return self._frame

    async def get_wire_device_summary(self):
        return {
            wire_device_id(wire, height): {"readings": 1, "last_seen": self._last_seen}
            for wire in wire_ids()
            for height in (1,)
        }


def _readings(temp_by_wire: dict[str, float]) -> pd.DataFrame:
    records = []
    for wire, temp in temp_by_wire.items():
        for section in deps.growth_sections:
            for hour in range(HOURS):
                records.append({
                    "device": wire_device_id(wire, section.height),
                    "height": section.height,
                    "measurement": "temp",
                    "time": DAY + timedelta(hours=hour),
                    "value": temp,
                })
    return wire_readings_frame(records)


@pytest.fixture(scope="module")
def app():
    from wp6_data.shared.templates import config as tmpl_config

    saved = (
        tmpl_config._dashboard_id,
        tmpl_config._dashboard_title,
        tmpl_config._twin_theme_css,
        tmpl_config._data_sources,
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
            tmpl_config._dashboard_id,
            tmpl_config._dashboard_title,
            tmpl_config._twin_theme_css,
            tmpl_config._data_sources,
        ) = saved


@pytest.fixture
def client(app, monkeypatch):
    def _make(frame: pd.DataFrame):
        monkeypatch.setattr(deps, "db", _StubDb(frame))
        c = TestClient(app)
        c.__enter__()
        assert c.get("/auth/login", follow_redirects=False).status_code == 302
        return c

    made = []

    def _factory(frame):
        c = _make(frame)
        made.append(c)
        return c

    yield _factory
    for c in made:
        c.__exit__(None, None, None)


class TestHubRegistration:
    def test_uniformity_view_is_listed(self):
        hrefs = {v["href"] for v in MULTI_HEIGHT_VIEWS}
        assert UNIFORMITY_PATH in hrefs

    def test_landing_page_offers_it(self, client):
        resp = client(_readings({})).get("/multi_height")
        assert resp.status_code == 200
        assert UNIFORMITY_PATH in resp.text


class TestUniformityPage:
    def test_renders_without_naming_a_wire(self, client):
        resp = client(_readings({w: 20.0 for w in wire_ids()})).get(UNIFORMITY_PATH)

        assert resp.status_code == 200
        # Every declared wire gets a column — the page never picks one for you.
        for wire in wire_ids():
            assert wire in resp.text

    def test_a_silent_day_renders_rather_than_500s(self, client):
        """The empty readings frame used to raise on the day filter's ``.dt``."""
        resp = client(wire_readings_frame([])).get(f"{UNIFORMITY_PATH}?date=2020-01-01")

        assert resp.status_code == 200
        assert "excluded" in resp.text

    def test_every_metric_is_selectable(self, client):
        c = client(_readings({w: 20.0 for w in wire_ids()}))
        for metric in CROP_METRICS:
            assert c.get(f"{UNIFORMITY_PATH}?metric={metric}").status_code == 200

    def test_an_unknown_metric_falls_back_rather_than_erroring(self, client):
        c = client(_readings({w: 20.0 for w in wire_ids()}))

        resp = c.get(f"{UNIFORMITY_PATH}?metric=nonsense")

        assert resp.status_code == 200
        # The default metric's pill is the selected one, so the reader can see
        # which question the page actually answered.
        assert (
            f'class="group-btn active" style="text-decoration:none;" '
            f'href="{UNIFORMITY_PATH}?metric={DEFAULT_UNIFORMITY_METRIC}'
        ) in resp.text

    def test_the_metric_pills_keep_the_chosen_date(self, client):
        resp = client(_readings({w: 20.0 for w in wire_ids()})).get(
            f"{UNIFORMITY_PATH}?date=2026-08-12&metric=hum"
        )

        assert "date=2026-08-12" in resp.text

    def test_the_date_form_keeps_the_chosen_metric(self, client):
        resp = client(_readings({w: 20.0 for w in wire_ids()})).get(
            f"{UNIFORMITY_PATH}?metric=co2"
        )

        assert '<input type="hidden" name="metric" value="co2">' in resp.text

    def test_wire_columns_link_into_the_single_wire_page(self, client):
        resp = client(_readings({w: 20.0 for w in wire_ids()})).get(UNIFORMITY_PATH)

        first = wire_ids()[0]
        assert f"/multi_height/crop-climate?wire={first}&date=" in resp.text

    def test_a_drifting_wire_is_reported_as_an_offset(self, client):
        wires = wire_ids()
        drift = CONFIG.notable_spread["temp"] * 3
        temps = {w: 20.0 for w in wires}
        temps[wires[1]] = 20.0 + drift

        resp = client(_readings(temps)).get(UNIFORMITY_PATH)

        assert "consistent offset" in resp.text
        assert f"{drift:+.2f}" in resp.text

    def test_agreeing_wires_say_so(self, client):
        resp = client(_readings({w: 20.0 for w in wire_ids()})).get(UNIFORMITY_PATH)

        assert "agrees with the other wires" in resp.text
        assert "consistent offset" not in resp.text
