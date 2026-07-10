"""WP6 Red Dashboard - MySQL-backed sensor visualization with DLI analysis."""

from pathlib import Path

import structlog

from wp6_data.db.pool import close_pool, init_pool
from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection
from wp6_data.red.provider import RedSensorProvider
from wp6_data.red.routes import browse, dli, dli_model, multi_height, sijia
from wp6_data.red.routes import charts as red_charts
from wp6_data.red.routes.dli_model.train import train_model_from_db
from wp6_data.red.routes.sijia.card import render_sijia_card
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.red.wires import undeclared_wire_ids
from wp6_data.shared import render_card
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.twin import DataSource, ThemeColors, TwinConfig

log = structlog.get_logger()


async def _startup() -> None:
    """Connect to MySQL, bootstrap red TSDB schema, and train DLI model if needed."""
    deps.db = MySQLConnection(
        host=deps.DB_HOST,
        port=deps.DB_PORT,
        user=deps.DB_USER,
        password=deps.DB_PASSWORD,
        database=deps.DB_NAME,
    )
    await deps.db.connect()

    undeclared = await undeclared_wire_ids(deps.db)
    if undeclared:
        log.warning("wire_sensors_undeclared", wires=undeclared)

    pool = await init_pool(deps.settings.tsdb_url)
    await ensure_schema_red(pool)

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


async def _shutdown() -> None:
    if deps.db:
        await deps.db.close()
    await close_pool()


def _dli_card() -> str:
    return render_card(
        "Light Analysis (DLI)",
        '<a href="/dli" role="button">DLI Dashboard</a>',
        description="Daily Light Integral analysis and optimization tools.",
        card_class="card-bg card-bg-sun",
    )

def _multi_height_card() -> str:
    return render_card(
        "Multi Height",
        '<a href="/multi_height" role="button">Multi Height Views</a>',
        description="Visual overview of sensor data at multiple heights.",
        card_class="card-bg card-bg-multi-height",
    )


config = TwinConfig(
    twin_id="red",
    title="SPoHF Red Digital Twin",
    data_sources=[
        DataSource(
            key="mysql", label="GTL (MySQL, LoRaWAN)",
            provider=RedSensorProvider(metadata=deps.metadata),
        ),
    ],
    metadata=deps.metadata,
    export_dir=Path(deps.settings.export_dir),
    theme=ThemeColors(
        primary="#dc2626", primary_light="#ef4444", primary_dark="#b91c1c",
        accent="#f97316", surface_rgb="220, 38, 38",
    ),

    extra_routers=[browse.router, 
                   dli.router, 
                   dli_model.router, 
                   red_charts.router,
                   multi_height.router, 
                   sijia.router],
    hero_cards=[_dli_card, _multi_height_card],
    status_extras=[render_sijia_card],

    home_extra_html=(
        '<a href="/static/red/sensor_locations.docx" download role="button"'
        ' class="outline" style="width:100%">'
        "Download Sensor Device Identification (docx)</a>"
    ),
    lifespan_startup=_startup,
    lifespan_shutdown=_shutdown,
)

app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    from wp6_data.shared.compat import run_async

    async def _serve() -> None:
        cfg = uvicorn.Config(app, host="0.0.0.0", port=8000)
        await uvicorn.Server(cfg).serve()

    run_async(_serve())
