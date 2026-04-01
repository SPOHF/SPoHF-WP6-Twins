"""App factory: create a complete sensor dashboard from a TwinConfig."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from wp6_data.shared.auth import NotAuthenticated, verify_session_user
from wp6_data.shared.export import make_download_router
from wp6_data.shared.routes import api, charts, dashboard_page, health, home, status
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.templates import _current_user, configure_dashboard
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

# Static files live at the project root (4 dirs up from shared/app_factory.py)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


async def _set_user_context(request: Request, call_next):
    token = _current_user.set(request.session.get("user"))
    try:
        return await call_next(request)
    finally:
        _current_user.reset(token)


def _noop_auth() -> None:
    """No-op auth dependency for public twins."""


def _make_provider_dependency(config: TwinConfig):
    """Build a get_provider override that dispatches by cookie for multi-source twins."""
    sources_by_key = {ds.key: ds.provider for ds in config.data_sources}
    default = config.default_provider
    cookie_name = f"wp6_{config.twin_id}_source"

    async def _resolve_provider(request: Request) -> SensorDataProvider:
        if len(config.data_sources) <= 1:
            return default
        active_key = request.cookies.get(cookie_name)
        return sources_by_key.get(active_key, default) if active_key else default

    return _resolve_provider


def create_app(config: TwinConfig) -> FastAPI:
    """Build a complete sensor dashboard app from configuration."""
    configure_dashboard(
        config.twin_id,
        title=config.title,
        theme=config.theme,
        data_sources=config.data_sources,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if config.require_auth:
            from wp6_data.config import OIDCSettings
            from wp6_data.shared.auth import startup_oidc

            await startup_oidc(OIDCSettings())
        if config.lifespan_startup:
            await config.lifespan_startup()
        yield
        if config.lifespan_shutdown:
            await config.lifespan_shutdown()

    app = FastAPI(title=config.title, lifespan=lifespan)

    # Store config on app state for shared route dependencies
    app.state.twin_config = config

    # Cookie-based provider dispatch (noop for single-source twins)
    app.dependency_overrides[get_provider] = _make_provider_dependency(config)

    # For public twins, disable auth on all shared routes
    if not config.require_auth:
        app.dependency_overrides[verify_session_user] = _noop_auth

    # Middleware
    if config.require_auth:
        from wp6_data.config import OIDCSettings

        session_secret = OIDCSettings().session_secret
        app.add_middleware(BaseHTTPMiddleware, dispatch=_set_user_context)
        app.add_middleware(SessionMiddleware, secret_key=session_secret)

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

    # Auth routes (only if auth is enabled)
    if config.require_auth:
        from wp6_data.config import OIDCSettings
        from wp6_data.shared.auth import make_auth_router

        app.include_router(make_auth_router(OIDCSettings()))

    # Shared routes
    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(home.router)
    app.include_router(charts.router)
    app.include_router(dashboard_page.router)
    app.include_router(status.router)
    app.include_router(
        make_download_router(
            config.export_dir, sanitise=config.export_sanitise_names,
        ),
    )

    # Twin-specific routes
    for router in config.extra_routers:
        app.include_router(router)

    return app
