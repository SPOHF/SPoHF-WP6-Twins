"""WP6 Red Dashboard - MySQL-backed sensor visualization with authentication."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection
from wp6_data.red.routes import browse, charts, compare, dli, dli_model, export, health, home

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle."""
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
            stats = await dli_model.train_model_from_db(deps.db, deps.get_weather_client())
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


app = FastAPI(title="WP6 Red - Sensor Dashboard", lifespan=lifespan)

# Serve static files
if (deps.PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=deps.PROJECT_ROOT / "static"), name="static")

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
