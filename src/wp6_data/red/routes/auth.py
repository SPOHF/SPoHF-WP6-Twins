"""Authentication routes: login, callback, logout (Keycloak OIDC)."""

from urllib.parse import urlencode

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import RedirectResponse

from wp6_data.red import deps

router = APIRouter()


@router.get("/login")
async def login(request: Request, next: str = "/") -> RedirectResponse:
    """Redirect to Keycloak login page."""
    request.session["next"] = next
    redirect_uri = request.url_for("callback")
    return await deps.oauth.keycloak.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/callback")
async def callback(request: Request) -> RedirectResponse:
    """Handle OIDC callback from Keycloak."""
    token = await deps.oauth.keycloak.authorize_access_token(request)
    userinfo = token.get("userinfo", {})

    request.session["user"] = userinfo.get("preferred_username", "")
    request.session["email"] = userinfo.get("email", "")
    request.session["groups"] = userinfo.get("groups", [])

    next_url = request.session.pop("next", "/")
    return RedirectResponse(url=next_url)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear session and redirect to Keycloak logout."""
    request.session.clear()

    end_session_url = f"{deps.OIDC_ISSUER}/protocol/openid-connect/logout"
    params = urlencode({"post_logout_redirect_uri": str(request.base_url)})
    return RedirectResponse(url=f"{end_session_url}?{params}")
