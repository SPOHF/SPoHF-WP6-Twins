"""WP6 Blue Dashboard - TimescaleDB-backed sensor visualization."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from wp6_data.blue import deps
from wp6_data.blue.routes import api, charts, export, home, ops
from wp6_data.config import OIDCSettings, Settings
from wp6_data.shared.auth import NotAuthenticated, make_auth_router, startup_oidc
from wp6_data.shared.templates import _current_user

oidc_settings = OIDCSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_oidc(oidc_settings)
    settings = Settings()
    await deps.init_db(settings.tsdb_url)
    yield
    await deps.close_db()


async def _set_user_context(request: Request, call_next):
    token = _current_user.set(request.session.get("user"))
    try:
        return await call_next(request)
    finally:
        _current_user.reset(token)


app = FastAPI(title="SPoHF Blue Digital Twin", lifespan=lifespan)
app.add_middleware(BaseHTTPMiddleware, dispatch=_set_user_context)
app.add_middleware(SessionMiddleware, secret_key=oidc_settings.session_secret)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, _: NotAuthenticated) -> RedirectResponse:
    request.session["next"] = str(request.url)
    return RedirectResponse(url="/auth/login")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(deps.PROJECT_ROOT / "static" / "favicon.ico")

# Serve static files (logo, etc.) from project root
if (deps.PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=deps.PROJECT_ROOT / "static"), name="static")

app.include_router(make_auth_router(oidc_settings))
app.include_router(api.router)
app.include_router(ops.router)
app.include_router(home.router)
app.include_router(charts.router)
app.include_router(export.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
