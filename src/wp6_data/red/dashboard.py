"""WP6 Red Dashboard - MySQL-backed sensor visualization with authentication."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from wp6_data.config import OIDCSettings
from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection
from wp6_data.red.routes import browse, charts, compare, dli, dli_model, export, health, home
from wp6_data.red.routes.dli_model.train import train_model_from_db
from wp6_data.shared.auth import NotAuthenticated, make_auth_router, startup_oidc
from wp6_data.shared.templates import _current_user, configure_dashboard

configure_dashboard("red")

log = structlog.get_logger()

oidc_settings = OIDCSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle."""
    await startup_oidc(oidc_settings)
    deps.db = MySQLConnection(
        host=deps.DB_HOST,
        port=deps.DB_PORT,
        user=deps.DB_USER,
        password=deps.DB_PASSWORD,
        database=deps.DB_NAME,
    )
    await deps.db.connect()

    # Train DLI model on startup if not already saved on disk
    from wp6_data.red.dli import get_model

    model = get_model()
    if model.is_trained():
        log.info("dli_model_loaded_from_disk")
    else:
        try:
            stats = await train_model_from_db(deps.db, deps.get_weather_client())
            log.info(
                "dli_model_trained",
                r2=stats.r2_score,
                r2_stage1=stats.stage1.r2_score,
                r2_stage2=stats.stage2.r2_score,
                n_samples=stats.n_samples,
            )
        except Exception:
            log.warning("dli_model_training_failed", exc_info=True)

    yield
    await deps.db.close()


async def _set_user_context(request: Request, call_next):
    token = _current_user.set(request.session.get("user"))
    try:
        return await call_next(request)
    finally:
        _current_user.reset(token)


app = FastAPI(title="WP6 Red - Sensor Dashboard", lifespan=lifespan)
app.add_middleware(BaseHTTPMiddleware, dispatch=_set_user_context)
app.add_middleware(SessionMiddleware, secret_key=oidc_settings.session_secret)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, _: NotAuthenticated) -> RedirectResponse:
    request.session["next"] = str(request.url)
    return RedirectResponse(url="/auth/login")

# Serve static files
if (deps.PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=deps.PROJECT_ROOT / "static"), name="static")

app.include_router(make_auth_router(oidc_settings))
app.include_router(health.router)
app.include_router(home.router)
app.include_router(browse.router)
app.include_router(charts.router)
app.include_router(compare.router)
app.include_router(export.router)
app.include_router(dli.router)
app.include_router(dli_model.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
