"""WP6 Blue Dashboard - TimescaleDB-backed sensor visualization."""

from pathlib import Path

from wp6_data.blue import deps
from wp6_data.blue.provider import BlueSensorProvider
from wp6_data.blue.routes import charts as blue_charts
from wp6_data.blue.routes import ops
from wp6_data.config import Settings
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.twin import DataSource, ThemeColors, TwinConfig

settings = Settings()

YOOKR_PROJECT = "yookr-direct"


async def _startup() -> None:
    await deps.init_db(settings.tsdb_url)


async def _shutdown() -> None:
    await deps.close_db()


config = TwinConfig(
    twin_id="blue",
    title="SPoHF Blue Digital Twin",
    data_sources=[
        DataSource(
            key="spohf-datalake",
            label="SPoHF Datalake",
            provider=BlueSensorProvider(source_key="spohf-datalake"),
        ),
        DataSource(
            key="yookr",
            label="Yookr API",
            provider=BlueSensorProvider(
                project=YOOKR_PROJECT, source_key="yookr",
            ),
        ),
    ],
    metadata=deps.metadata,
    export_dir=Path(settings.blue_export_dir),
    theme=ThemeColors(
        primary="#2563eb", primary_light="#3b82f6", primary_dark="#1d4ed8",
        accent="#0ea5e9", surface_rgb="37, 99, 235",
    ),
    extra_routers=[ops.router, blue_charts.router],
    hero_cards=[],
    export_sanitise_names=True,
    lifespan_startup=_startup,
    lifespan_shutdown=_shutdown,
)

app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
