"""WP6 Blue Dashboard - TimescaleDB-backed sensor visualization."""

from pathlib import Path

from wp6_data.blue import deps
from wp6_data.blue import manual as blue_manual
from wp6_data.blue.explore import render_fertilization_strategies_tab
from wp6_data.blue.provider import BlueSensorProvider
from wp6_data.blue.routes import api as blue_api
from wp6_data.blue.routes import charts as blue_charts
from wp6_data.blue.routes import ops
from wp6_data.blue.routes.monitor import broken_sensors as broken_sensors_monitor
from wp6_data.blue.routes.monitor import legacy_router as legacy_monitor_router
from wp6_data.blue.routes.monitor import manual as manual_monitor
from wp6_data.blue.routes.monitor import mixed_views as mixed_views_monitor
from wp6_data.blue.routes.monitor import router as monitor_router
from wp6_data.config import Settings
from wp6_data.shared import render_card
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.twin import DataSource, ThemeColors, TwinConfig

settings = Settings()


def _gdd_card() -> str:
    return render_card(
        "GDD Tracker",
        '<a href="/sensor-monitor/gdd" role="button">GDD Dashboard</a>',
        description=(
            "Growing Degree Days — track cumulative heat for harvest "
            "prediction."
        ),
        card_class="card-bg card-bg-growth",
    )


def _monitor_card() -> str:
    return render_card(
        "Monitors",
        (
            '<a href="/sensor-monitor" role="button">Sensor Monitor</a>'
            ' <a href="/manual-monitor" role="button" class="outline">'
            'Manual Dashboards</a>'
            ' <a href="/mixed-views" role="button" class="outline">'
            'Mixed Views</a>'
            ' <a href="/broken-sensors" role="button" class="outline">'
            'Unreliable Sensors</a>'
        ),
        description=(
            "Sensor monitor (soil, light, microclimate) and manual "
            "measurement dashboards for uploaded long_data files."
        ),
    )

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
                project=YOOKR_PROJECT,
                source_key="yookr",
            ),
        ),
    ],
    metadata=deps.metadata,
    export_dir=Path(settings.blue_export_dir),
    theme=ThemeColors(
        primary="#2563eb", primary_light="#3b82f6", primary_dark="#1d4ed8",
        accent="#0ea5e9", surface_rgb="37, 99, 235",
    ),
    extra_routers=[
        ops.router,
        blue_api.router,
        blue_charts.router,
        monitor_router,
        legacy_monitor_router,
        manual_monitor.router,
        mixed_views_monitor.router,
        broken_sensors_monitor.router,
        *blue_manual.manual_routers(),
    ],
    explore_extra_tabs={
        "fertilization": (
            "Fertilization Strategies",
            render_fertilization_strategies_tab(),
        ),
    },
    hero_cards=[_gdd_card, _monitor_card],
    status_extras=blue_manual.manual_cards(),
    export_sanitise_names=True,
    # Authenticated twin (TwinConfig.require_auth defaults to True): the app
    # factory mounts SessionMiddleware, the /auth/* OIDC router, OIDC startup
    # and the NotAuthenticated redirect. Required for the admin-gated manual
    # upload UI; deployment must provide the WP6_OIDC_* secrets +
    # WP6_OIDC_REDIRECT_BASE for blue (handled in the Helm step).
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
