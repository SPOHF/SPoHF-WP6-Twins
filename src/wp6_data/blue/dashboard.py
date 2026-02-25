"""WP6 Blue Dashboard - Neo4j-backed sensor visualization."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from wp6_data.blue import deps
from wp6_data.blue.routes import charts, compare, home, ops


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    deps.close_driver()


app = FastAPI(title="WP6 Blue - Sensor Dashboard", lifespan=lifespan)

# Serve static files (logo, etc.) from project root
if (deps.PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=deps.PROJECT_ROOT / "static"), name="static")

app.include_router(ops.router)
app.include_router(home.router)
app.include_router(charts.router)
app.include_router(compare.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
