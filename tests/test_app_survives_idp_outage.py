"""An authenticated twin must still boot and serve when the OIDC provider is down.

This is the end-to-end cover for the 2026-07-13 outage. The unit tests in
tests/test_auth_oidc_discovery.py pin `ensure_endpoints`' behaviour; this one
pins the thing that actually hurt: `create_app`'s lifespan used to propagate the
discovery failure, so uvicorn logged "Application startup failed. Exiting." and
the container died. /health, the public pages and the static assets all went
down with it — because the app could not pre-cache four URLs it did not need yet.

Every other app test strips the lifespan and runs with dev-auth, which is exactly
why nothing caught this.
"""

import os

os.environ.setdefault("WP6_OIDC_CLIENT_SECRET", "test-secret")
os.environ.setdefault("WP6_OIDC_SESSION_SECRET", "test-session-secret-test-session")

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

import wp6_data.blue
from wp6_data.shared import auth
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.twin import DataSource, ThemeColors, TwinConfig

_METADATA = Path(wp6_data.blue.__file__).parent / "metadata.yaml"


@pytest.fixture(autouse=True)
def _isolate_dashboard_globals():
    """create_app mutates shared template + auth module globals; restore them."""
    from wp6_data.shared.templates import config as tmpl_config

    saved = (
        tmpl_config._dashboard_id,
        tmpl_config._dashboard_title,
        tmpl_config._twin_theme_css,
        tmpl_config._data_sources,
    )
    yield
    (
        tmpl_config._dashboard_id,
        tmpl_config._dashboard_title,
        tmpl_config._twin_theme_css,
        tmpl_config._data_sources,
    ) = saved
    auth._endpoints = {}
    auth._dev_auth = False
    auth._issuer = ""


@pytest.fixture
def idp_down(monkeypatch):
    """The real outage: the issuer's TLS certificate has expired."""

    async def _boom(self, url, **kwargs):
        raise httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "certificate has expired",
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", _boom)


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("WP6_OIDC_DEV_AUTH", "false")
    monkeypatch.setenv("WP6_OIDC_REDIRECT_BASE", "https://twin.example")
    monkeypatch.setenv("WP6_OIDC_ISSUER", "https://idp.example/realms/spohf")

    return create_app(
        TwinConfig(
            twin_id="test-twin",
            title="Test Twin",
            data_sources=[DataSource(key="k", label="L", provider=AsyncMock())],
            metadata=MetadataRegistry(_METADATA),
            export_dir=Path(tmp_path),
            theme=ThemeColors(
                primary="#000", primary_light="#111", primary_dark="#222",
                accent="#333", surface_rgb="0, 0, 0",
            ),
            # The property under test: an authenticated twin whose provider is down.
            require_auth=True,
        ),
    )


def test_app_boots_and_serves_health_while_idp_is_down(app, idp_down):
    """Entering the TestClient context runs the real lifespan — it must not raise."""
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_login_degrades_to_503_while_idp_is_down(app, idp_down):
    with TestClient(app) as client:
        resp = client.get("/auth/login", follow_redirects=False)

    assert resp.status_code == 503


def test_login_works_once_the_idp_recovers_without_a_restart(app, idp_down, monkeypatch):
    """The whole point: no pod restart needed when someone renews the certificate."""
    with TestClient(app) as client:
        assert client.get("/auth/login", follow_redirects=False).status_code == 503

        async def _recovered(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": "https://idp.example/auth",
                    "token_endpoint": "https://idp.example/token",
                    "userinfo_endpoint": "https://idp.example/userinfo",
                },
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", _recovered)

        resp = client.get("/auth/login", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://idp.example/auth?")
