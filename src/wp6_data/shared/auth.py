"""Shared OIDC authentication utilities for both dashboards."""

import asyncio
import hashlib
import os
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from wp6_data.config import OIDCSettings

log = structlog.get_logger()

_endpoints: dict[str, str] = {}
_dev_auth: bool = False
_issuer: str = ""
_discovery_lock = asyncio.Lock()


class NotAuthenticated(Exception):
    pass


async def _fetch_discovery(issuer: str) -> dict[str, str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{issuer}/.well-known/openid-configuration")
        resp.raise_for_status()
        doc = resp.json()
    return {
        "authorization_endpoint": doc["authorization_endpoint"],
        "token_endpoint": doc["token_endpoint"],
        "userinfo_endpoint": doc["userinfo_endpoint"],
        "end_session_endpoint": doc.get("end_session_endpoint", ""),
    }


async def startup_oidc(settings: OIDCSettings) -> None:
    """Validate OIDC config and warm the discovery cache.

    Fails fast on our own misconfiguration, but *not* on the identity provider
    being unhealthy. The provider is somebody else's service; a bad certificate
    or a restart there must not stop this dashboard from serving its public
    pages and /health. Discovery is retried lazily on the first auth request
    (see `ensure_endpoints`), so a recovered provider needs no pod restart.
    """
    global _endpoints, _dev_auth, _issuer
    if settings.dev_auth:
        # Sanity check
        if settings.redirect_base:
            raise RuntimeError(
                "WP6_OIDC_DEV_AUTH cannot be enabled when WP6_OIDC_REDIRECT_BASE is set — "
                "dev auth must not be used in production"
            )
        _dev_auth = True
        return
    if not settings.client_secret:
        raise RuntimeError("WP6_OIDC_CLIENT_SECRET is not set")
    if not settings.session_secret:
        raise RuntimeError("WP6_OIDC_SESSION_SECRET is not set")
    _issuer = settings.issuer
    try:
        _endpoints = await _fetch_discovery(settings.issuer)
    except Exception:
        _endpoints = {}
        log.warning("oidc_discovery_failed_at_startup", issuer=settings.issuer, exc_info=True)


async def ensure_endpoints() -> dict[str, str]:
    """Return the cached OIDC endpoints, re-fetching if startup discovery failed.

    Raises 503 rather than propagating the transport error, so a provider outage
    degrades authentication instead of the whole application.
    """
    global _endpoints
    if _endpoints:
        return _endpoints
    async with _discovery_lock:
        if _endpoints:
            return _endpoints
        try:
            _endpoints = await _fetch_discovery(_issuer)
        except Exception as exc:
            log.warning("oidc_discovery_failed", issuer=_issuer, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Identity provider unavailable — try again shortly.",
            ) from exc
    return _endpoints


def _pkce_pair() -> tuple[str, str]:
    verifier = urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
    challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def make_auth_router(settings: OIDCSettings) -> APIRouter:
    router = APIRouter(prefix="/auth")
    redirect_uri = f"{settings.redirect_base}/auth/callback"

    @router.get("/login")
    async def login(request: Request):
        if _dev_auth:
            request.session["user"] = "dev-user"
            request.session["groups"] = ["/wp6-admins"]
            next_url = request.session.pop("next", "/")
            return RedirectResponse(url=next_url, status_code=302)
        endpoints = await ensure_endpoints()
        verifier, challenge = _pkce_pair()
        state = urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
        request.session["code_verifier"] = verifier
        request.session["state"] = state
        params = {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return RedirectResponse(url=f"{endpoints['authorization_endpoint']}?{urlencode(params)}")

    @router.get("/callback")
    async def callback(
        request: Request,
        code: str = "",
        state: str = "",
        error: str = "",
    ):
        if error:
            raise HTTPException(status_code=400, detail=f"OIDC error: {error}")

        stored_state = request.session.pop("state", None)
        if not stored_state or stored_state != state:
            return RedirectResponse(url="/auth/login", status_code=302)

        code_verifier = request.session.pop("code_verifier", None)
        if not code_verifier:
            return RedirectResponse(url="/auth/login", status_code=302)

        endpoints = await ensure_endpoints()
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                endpoints["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "code_verifier": code_verifier,
                },
            )
            if token_resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Token exchange failed")

            userinfo_resp = await client.get(
                endpoints["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {token_resp.json()['access_token']}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()

        request.session["user"] = userinfo.get("preferred_username") or userinfo["sub"]
        request.session["groups"] = userinfo.get("groups", [])
        request.session["id_token"] = token_resp.json().get("id_token", "")

        next_url = request.session.pop("next", "/")
        return RedirectResponse(url=next_url, status_code=302)

    @router.get("/logout")
    async def logout(request: Request):
        id_token = request.session.pop("id_token", "")
        request.session.pop("user", None)
        request.session.pop("groups", None)
        # The local session is already gone, so a provider outage must not turn
        # logout into a 503 — degrade to a local-only logout instead.
        try:
            end_session = (await ensure_endpoints()).get("end_session_endpoint", "")
        except HTTPException:
            end_session = ""
        if end_session:
            params = urlencode({
                "post_logout_redirect_uri": f"{settings.redirect_base}/",
                "id_token_hint": id_token,
            })
            return RedirectResponse(url=f"{end_session}?{params}")
        return RedirectResponse(url="/auth/login")

    return router


def verify_session_user(request: Request) -> str:
    """FastAPI dependency: returns username from session, raises NotAuthenticated if missing."""
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


def _is_in_admin_group(request: Request) -> bool:
    return "/wp6-admins" in request.session.get("groups", [])


def verify_session_admin(request: Request) -> str:
    """FastAPI dependency: returns username if user is in the wp6-admins group."""
    user = verify_session_user(request)
    if not _is_in_admin_group(request):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def is_admin(request: Request) -> bool:
    """Check if the current session user is in the wp6-admins group."""
    return _is_in_admin_group(request)
