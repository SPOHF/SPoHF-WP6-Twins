"""App factory: create a complete sensor dashboard from a TwinConfig."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from wp6_data.config import OIDCSettings
from wp6_data.shared.auth import NotAuthenticated, make_auth_router, startup_oidc
from wp6_data.shared.export import make_download_router
from wp6_data.shared.provider import TwinConfig
from wp6_data.shared.routes import api, charts, dashboard_page, health, home
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.templates import _current_user, configure_dashboard

# Static files live at the project root (4 dirs up from shared/app_factory.py)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


async def _set_user_context(request: Request, call_next):
    token = _current_user.set(request.session.get("user"))
    try:
        return await call_next(request)
    finally:
        _current_user.reset(token)


def create_app(config: TwinConfig) -> FastAPI:
    """Build a complete sensor dashboard app from configuration."""
    oidc_settings = OIDCSettings()
    configure_dashboard(config.twin_id)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await startup_oidc(oidc_settings)
        if config.lifespan_startup:
            await config.lifespan_startup()
        yield
        if config.lifespan_shutdown:
            await config.lifespan_shutdown()

    app = FastAPI(title=config.title, lifespan=lifespan)

    # Store config on app state for shared route dependencies
    app.state.twin_config = config

    # If the twin provides a per-request provider dependency (e.g. blue's
    # cookie-based source dispatch), override the default get_provider
    if config.provider_dependency is not None:
        app.dependency_overrides[get_provider] = config.provider_dependency

    # Middleware (order matters: session must be added last to be outermost)
    app.add_middleware(BaseHTTPMiddleware, dispatch=_set_user_context)
    app.add_middleware(SessionMiddleware, secret_key=oidc_settings.session_secret)

    # Exception handler for unauthenticated requests
    @app.exception_handler(NotAuthenticated)
    async def not_authenticated_handler(
        request: Request, _: NotAuthenticated,
    ) -> RedirectResponse:
        request.session["next"] = str(request.url)
        return RedirectResponse(url="/auth/login")

    # Favicon and static files
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(PROJECT_ROOT / "static" / "favicon.ico")

    static_dir = PROJECT_ROOT / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Shared routes
    app.include_router(make_auth_router(oidc_settings))
    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(home.router)
    app.include_router(charts.router)
    app.include_router(dashboard_page.router)
    app.include_router(
        make_download_router(
            config.export_dir, sanitise=config.export_sanitise_names,
        ),
    )

    # Twin-specific routes
    for router in config.extra_routers:
        app.include_router(router)

    return app
