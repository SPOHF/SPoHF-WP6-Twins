"""OIDC discovery must not make the identity provider a hard boot dependency.

Regression cover for the 2026-07-13 outage: Keycloak's TLS certificate expired,
`startup_oidc` raised out of the FastAPI lifespan, and both dashboards
crash-looped (21 restarts each) until someone else renewed the certificate.
While it was down, *nothing* served — not /health, not the public pages —
because the app could not pre-cache four URLs it would not need until a user
clicked "log in".

The rule these tests pin down: fail fast on our own misconfiguration, fail soft
on an external dependency being briefly unhealthy.
"""

import httpx
import pytest
from fastapi import HTTPException

from wp6_data.config import OIDCSettings
from wp6_data.shared import auth

DISCOVERY_DOC = {
    "authorization_endpoint": "https://idp.example/auth",
    "token_endpoint": "https://idp.example/token",
    "userinfo_endpoint": "https://idp.example/userinfo",
    "end_session_endpoint": "https://idp.example/logout",
}


@pytest.fixture(autouse=True)
def _reset_auth_globals():
    """`auth` caches discovery in module globals; isolate every test from them."""
    yield
    auth._endpoints = {}
    auth._dev_auth = False
    auth._issuer = ""


def _settings(**overrides) -> OIDCSettings:
    # dev_auth is pinned off: OIDCSettings reads .env, and a developer's local
    # WP6_OIDC_DEV_AUTH would otherwise short-circuit every case below.
    return OIDCSettings(**{
        "issuer": "https://idp.example/realms/spohf",
        "client_secret": "s3cret",
        "session_secret": "sess",
        "redirect_base": "https://twin.example",
        "dev_auth": False,
        **overrides,
    })


@pytest.fixture
def provider_down(monkeypatch):
    """Simulate the real outage: TLS verification fails against the issuer."""

    async def _boom(self, url, **kwargs):
        raise httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "certificate has expired",
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", _boom)


@pytest.fixture
def provider_up(monkeypatch):
    """Issuer serves a well-formed discovery document."""

    async def _ok(self, url, **kwargs):
        return httpx.Response(200, json=DISCOVERY_DOC, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _ok)


async def test_startup_survives_an_unreachable_provider(provider_down):
    """The outage case: startup must NOT raise, so the app still boots and serves."""
    await auth.startup_oidc(_settings())

    assert auth._endpoints == {}, "endpoints should be left uncached, not fabricated"


async def test_startup_still_fails_fast_on_missing_config(provider_up):
    """A missing client secret is *our* bug and will never self-heal — crash loudly."""
    with pytest.raises(RuntimeError, match="WP6_OIDC_CLIENT_SECRET"):
        await auth.startup_oidc(_settings(client_secret=""))

    with pytest.raises(RuntimeError, match="WP6_OIDC_SESSION_SECRET"):
        await auth.startup_oidc(_settings(session_secret=""))


async def test_discovery_is_retried_lazily_once_the_provider_recovers(
    monkeypatch, provider_down,
):
    """No restart required: the next auth request re-fetches and succeeds."""
    await auth.startup_oidc(_settings())
    assert auth._endpoints == {}

    # Keycloak's certificate gets renewed.
    async def _ok(self, url, **kwargs):
        return httpx.Response(200, json=DISCOVERY_DOC, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _ok)

    endpoints = await auth.ensure_endpoints()

    assert endpoints == DISCOVERY_DOC
    assert auth._endpoints == DISCOVERY_DOC, "recovered endpoints should be cached"


async def test_auth_request_while_provider_down_is_a_503_not_a_crash(provider_down):
    """Login degrades to a clear 503; it must not take the process down."""
    await auth.startup_oidc(_settings())

    with pytest.raises(HTTPException) as exc:
        await auth.ensure_endpoints()

    assert exc.value.status_code == 503


async def test_healthy_startup_caches_endpoints_up_front(provider_up):
    """The happy path is unchanged: discovery is still done eagerly at boot."""
    await auth.startup_oidc(_settings())

    assert auth._endpoints == DISCOVERY_DOC
