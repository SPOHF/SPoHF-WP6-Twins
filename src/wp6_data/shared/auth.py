"""Shared OIDC authentication utilities for both dashboards."""

import hashlib
import os
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from wp6_data.config import OIDCSettings

_endpoints: dict[str, str] = {}


class NotAuthenticated(Exception):
    pass


async def startup_oidc(settings: OIDCSettings) -> None:
    """Fetch OIDC discovery document and cache endpoints."""
    if not settings.client_secret:
        raise RuntimeError("WP6_OIDC_CLIENT_SECRET is not set")
    if not settings.session_secret:
        raise RuntimeError("WP6_OIDC_SESSION_SECRET is not set")
    global _endpoints
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.issuer}/.well-known/openid-configuration")
        resp.raise_for_status()
        doc = resp.json()
    _endpoints = {
        "authorization_endpoint": doc["authorization_endpoint"],
        "token_endpoint": doc["token_endpoint"],
        "userinfo_endpoint": doc["userinfo_endpoint"],
        "end_session_endpoint": doc.get("end_session_endpoint", ""),
    }


def _pkce_pair() -> tuple[str, str]:
    verifier = urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
    challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def make_auth_router(settings: OIDCSettings) -> APIRouter:
    router = APIRouter(prefix="/auth")
    redirect_uri = f"{settings.redirect_base}/auth/callback"

    @router.get("/login")
    async def login(request: Request):
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
        return RedirectResponse(url=f"{_endpoints['authorization_endpoint']}?{urlencode(params)}")

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
            raise HTTPException(status_code=400, detail="Invalid state parameter")

        code_verifier = request.session.pop("code_verifier", None)
        if not code_verifier:
            raise HTTPException(status_code=400, detail="Missing code verifier")

        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                _endpoints["token_endpoint"],
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
                _endpoints["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {token_resp.json()['access_token']}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()

        request.session["user"] = userinfo.get("preferred_username") or userinfo["sub"]
        request.session["groups"] = userinfo.get("groups", [])

        next_url = request.session.pop("next", "/")
        return RedirectResponse(url=next_url, status_code=302)

    @router.get("/logout")
    async def logout(request: Request):
        request.session.pop("user", None)
        request.session.pop("groups", None)
        end_session = _endpoints.get("end_session_endpoint", "")
        if end_session:
            params = urlencode({"post_logout_redirect_uri": f"{settings.redirect_base}/"})
            return RedirectResponse(url=f"{end_session}?{params}")
        return RedirectResponse(url="/auth/login")

    return router


def verify_session_user(request: Request) -> str:
    """FastAPI dependency: returns username from session, raises NotAuthenticated if missing."""
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


def verify_session_admin(request: Request) -> str:
    """FastAPI dependency: returns username if user is in the wp6-admins group."""
    user = verify_session_user(request)
    if "wp6-admins" not in request.session.get("groups", []):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def is_admin(request: Request) -> bool:
    """Check if the current session user is in the wp6-admins group."""
    return "wp6-admins" in request.session.get("groups", [])
