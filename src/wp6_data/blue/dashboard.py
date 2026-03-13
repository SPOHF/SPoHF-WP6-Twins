"""WP6 Blue Dashboard - Neo4j-backed sensor visualization."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from wp6_data.blue import deps
from wp6_data.blue.routes import charts, compare, home, ops
from wp6_data.config import OIDCSettings
from wp6_data.shared.auth import NotAuthenticated, make_auth_router, startup_oidc

oidc_settings = OIDCSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_oidc(oidc_settings)
    yield
    deps.close_driver()


app = FastAPI(title="WP6 Blue - Sensor Dashboard", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=oidc_settings.session_secret)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, _: NotAuthenticated) -> RedirectResponse:
    request.session["next"] = str(request.url)
    return RedirectResponse(url="/auth/login")

# Serve static files (logo, etc.) from project root
if (deps.PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=deps.PROJECT_ROOT / "static"), name="static")

app.include_router(make_auth_router(oidc_settings))
app.include_router(ops.router)
app.include_router(home.router)
app.include_router(charts.router)
app.include_router(compare.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
