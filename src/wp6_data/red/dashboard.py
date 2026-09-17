"""WP6 Red Dashboard - MySQL-backed sensor visualization with DLI analysis."""

import asyncio
import time
from pathlib import Path

import structlog

from wp6_data.db.pool import close_pool, init_pool
from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection
from wp6_data.red.provider import RedSensorProvider
from wp6_data.red.routes import (
    browse,
    climate_forecast,
    climate_model,
    crop_cycles,
    dli,
    dli_model,
    multi_height,
    sijia,
)
from wp6_data.red.routes import charts as red_charts
from wp6_data.red.routes.dli_model.train import train_model_from_db
from wp6_data.red.routes.sijia.card import render_sijia_card
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.red.wires import undeclared_wire_ids
from wp6_data.shared import render_card
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.scheduling import parse_daily_time, run_daily
from wp6_data.shared.twin import DataSource, ThemeColors, TwinConfig

log = structlog.get_logger()


# Holds the background boot-training tasks so they aren't garbage-collected
# before they run to completion, and the nightly schedule for the same reason —
# `run_daily` never returns, so its task must outlive this module's import.
_bootstrap_task: asyncio.Task | None = None
_climate_bootstrap_task: asyncio.Task | None = None
_retrain_task: asyncio.Task | None = None


async def _train_dli_model_if_missing() -> None:
    from wp6_data.red.dli import get_model

    model = get_model()
    if model.is_trained():
        log.info("dli_model_loaded_from_disk")
        return
    try:
        started = time.monotonic()
        stats = await train_model_from_db(deps.db, deps.get_weather_client())
        log.info(
            "dli_model_trained",
            seconds=round(time.monotonic() - started, 1),
            r2=stats.r2_score,
            r2_stage1=stats.stage1.r2_score,
            r2_stage2=stats.stage2.r2_score,
            n_samples=stats.n_samples,
        )
    except Exception:
        log.warning("dli_model_training_failed", exc_info=True)


async def _train_climate_model_if_missing() -> None:
    """Fit the climate chain on boot when no saved copy is readable.

    With the model on a PVC this is now the *exception* rather than the rule: a
    deploy finds the artifact already there and skips straight past. It still
    fires on a first install, whenever `MODEL_VERSION` has moved on, and
    whenever the config fingerprint no longer matches — which is how a schema
    or metadata change forces a refit without anyone remembering to.

    Never raises: a failure here must not take down startup, and the admin
    Retrain button remains the fallback.
    """
    from wp6_data.red.climate.config import load_climate_model
    from wp6_data.red.climate.training import load_chain

    # Config-aware: a saved model fitted under a different metadata.yaml is not
    # a model we can use, so it refits here rather than being served.
    if load_chain(load_climate_model(deps._METADATA_PATH)) is not None:
        log.info("climate_model_loaded_from_disk")
        return
    try:
        started = time.monotonic()
        chain = await _retrain_climate_model()
        if chain is None:
            return
        log.info(
            "climate_model_trained",
            seconds=round(time.monotonic() - started, 1),
            reference=chain.chosen_reference,
            span_days=chain.span_days,
            beat_persistence=len(chain.stats.horizons_beating_persistence)
            if chain.stats else 0,
            suggestions=len(chain.suggestions),
        )
    except Exception:
        log.warning("climate_model_training_failed", exc_info=True)


async def _retrain_climate_model():
    """One retrain, through the lock the admin button and boot also hold."""
    from wp6_data.red.climate.config import load_climate_model
    from wp6_data.red.climate.training import train_chain_guarded

    return await train_chain_guarded(
        load_climate_model(deps._METADATA_PATH), deps.get_weather_client()
    )


async def _nightly_retrain() -> None:
    """Refit both red models against everything recorded since the last run.

    This is what keeps a persisted model honest. The artifact now survives a
    deploy, so without a clock it would be refitted only on a cold boot and
    would quietly stop improving — and for the climate chain that is a real
    loss, because retraining is also when it re-decides whether link 3 has
    enough winter to earn its day-of-year term and which greenhouse-level
    reference wins.

    The two are refitted in sequence rather than together: they are CPU-bound
    and share a single-replica pod, and nothing is waiting on them at 03:00.
    """
    # Timed, because the fits are CPU-bound and the pod's CPU limit is a
    # fraction of a core: the same work that takes ~1 min on a workstation takes
    # far longer here, and the only way to tell how much is to record it.
    started = time.monotonic()
    chain = await _retrain_climate_model()
    climate_seconds = time.monotonic() - started
    log.info(
        "climate_model_retrained",
        skipped=chain is None,
        span_days=chain.span_days if chain else 0,
        seconds=round(climate_seconds, 1),
    )

    started = time.monotonic()
    stats = await train_model_from_db(deps.db, deps.get_weather_client())
    log.info(
        "dli_model_retrained",
        r2=stats.r2_score,
        n_samples=stats.n_samples,
        seconds=round(time.monotonic() - started, 1),
    )


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

    # Both models are read back from the models volume when it holds a usable
    # artifact, so these are no-ops on an ordinary deploy. Still backgrounded:
    # a first install, or a MODEL_VERSION bump, does a full cold fit, and a slow
    # one must not delay readiness — mirrors blue's soil-forecast bootstrap.
    global _bootstrap_task, _climate_bootstrap_task, _retrain_task
    _bootstrap_task = asyncio.create_task(_train_dli_model_if_missing())
    _climate_bootstrap_task = asyncio.create_task(_train_climate_model_if_missing())

    # Models persist across deploys now, so a schedule is what keeps them
    # current. Unset means no schedule, which is what a dev machine wants.
    at = parse_daily_time(deps.settings.retrain_at)
    if at is not None:
        _retrain_task = asyncio.create_task(
            run_daily(_nightly_retrain, at=at, name="red_model_retrain")
        )


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

def _crop_cycles_card() -> str:
    return render_card(
        "Crop Cycles",
        '<a href="/crop-cycles/" role="button">Cohort Waterfall</a>',
        description="Overlapping 8-week fruit cohorts against the climate they grew in.",
        card_class="card-bg card-bg-cycles",
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
                   climate_model.router,
                   climate_forecast.router,
                   red_charts.router,
                   multi_height.router, 
                   crop_cycles.router,
                   sijia.router],
    hero_cards=[_dli_card, _multi_height_card, _crop_cycles_card],
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
