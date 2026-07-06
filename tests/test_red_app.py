"""Smoke tests for the red dashboard app composed without infrastructure.

Builds the red app from its real TwinConfig with the lifespan hooks stripped,
so no MySQL connect, TSDB pool init or model training happens: ``deps.db``
stays ``None`` and each covered route must compose — either via its
"Database not connected" branch or (for the shared home) with the provider's
backends mocked per tests/test_red_provider.py.

dev-auth env is set before the app imports (see tests/test_series_endpoint.py).
"""

import os

os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")
os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "dev")
os.environ.setdefault("WP6_OIDC_SESSION_SECRET", "dev-session-secret-dev-session-secret")
os.environ.setdefault(
    "WP6_RED_TSDB_URL", "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red",
)

import dataclasses
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Importing red.dashboard runs create_app -> configure_dashboard, which
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
    from wp6_data.red.dashboard import config
    from wp6_data.shared.app_factory import create_app

    # Strip the lifespan hooks: no MySQL connect / TSDB pool / model training.
    test_config = dataclasses.replace(
        config, lifespan_startup=None, lifespan_shutdown=None,
    )
    app = create_app(test_config)
    try:
        with TestClient(app) as c:
            # Dev-auth login seeds the session cookie the routes require.
            resp = c.get("/auth/login", follow_redirects=False)
            assert resp.status_code == 302
            yield c
    finally:
        (
            tmpl_config._dashboard_id,
            tmpl_config._dashboard_title,
            tmpl_config._twin_theme_css,
            tmpl_config._data_sources,
        ) = saved


def test_multi_height_landing_renders_without_db(client):
    resp = client.get("/multi_height")
    assert resp.status_code == 200
    assert "Multi Height" in resp.text


def test_dli_home_renders_not_connected_page(client):
    from wp6_data.red.routes.dli.home import PAGE_TITLE

    resp = client.get("/dli")
    assert resp.status_code == 200
    assert "Database not connected" in resp.text
    assert PAGE_TITLE in resp.text


def test_dli_history_renders_not_connected_page(client):
    from wp6_data.red.routes.dli.history import PAGE_TITLE

    resp = client.get("/dli/history")
    assert resp.status_code == 200
    assert "Database not connected" in resp.text
    assert PAGE_TITLE in resp.text


def test_shared_home_composes_with_mocked_data_layer(client, monkeypatch):
    """GET / drives RedSensorProvider; back it with empty mocked backends."""
    from wp6_data.red import deps as red_deps
    from wp6_data.red import tsdb
    from wp6_data.red.dashboard import config
    from wp6_data.red.provider import _coverage_cache
    from wp6_data.shared import sensor_summary

    db = AsyncMock()
    db.get_all_devices.return_value = {}
    db.get_wire_device_summary.return_value = {}
    monkeypatch.setattr(red_deps, "db", db)
    monkeypatch.setattr(tsdb, "fetch_sensors_from_cagg", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        tsdb,
        "fetch_manual_summary_tsdb",
        AsyncMock(return_value={"uploads": {}, "measurements": {}}),
    )
    sensor_summary.invalidate()
    _coverage_cache.clear()
    try:
        resp = client.get("/")
        assert resp.status_code == 200
        assert config.title in resp.text
    finally:
        # Drop anything cached from the mocked backends.
        sensor_summary.invalidate()
        _coverage_cache.clear()
