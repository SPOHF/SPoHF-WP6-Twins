"""GET /sensor-monitor/soil/forecast — daily soil condition forecast (day+1..7)."""

import asyncio
import html
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from plotly.subplots import make_subplots

from wp6_data.blue.soil_forecaster import SoilForecaster, train_all_forecasters
from wp6_data.blue.treatments import (
    load_device_treatment_map,
    treatment_color,
)
from wp6_data.config import Settings
from wp6_data.shared import render_card, render_page
from wp6_data.shared.auth import is_admin, verify_session_admin
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

logger = logging.getLogger(__name__)

# Serialises retraining so two concurrent "Update" clicks don't write the same
# .pkl files at once; the second click is told training is already running.
_training_lock = asyncio.Lock()

PAGE_TITLE = "SPoHF Blue - Soil Forecast"

_FORECAST_SENSORS = ["soilTemperature", "soilMoisture"]
_SENSOR_META: dict[str, tuple[str, str]] = {
    "soilTemperature": ("Soil Temperature", "°C"),
    "soilMoisture":    ("Soil Moisture",    "%VWC"),
}
_SENSOR_ROWS = [("soilTemperature", 1), ("soilMoisture", 2)]
_RECENT_DAYS = 30  # days of history needed for lag features
_DEFAULT_TREATMENT = "Std"

_settings = Settings()
# Models live on ephemeral container storage (default: home dir), mirroring
# red's DLI model: a restart wipes them and the dashboard retrains on boot (see
# bootstrap_models_if_missing) rather than persisting to a PVC. Deliberately
# NOT under blue_export_dir — that PVC is the nightly CSV export, mounted
# read-only in the dashboard. Override the location with WP6_BLUE_MODEL_DIR.
_MODELS_DIR = (
    Path(_settings.blue_model_dir)
    if _settings.blue_model_dir
    else Path.home() / ".wp6" / "blue-models"
)

FORECAST_CSS = """
    .stats-grid { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .stats-grid article {
        flex: 1; min-width: 110px; text-align: center; padding: 0.5rem;
    }
    .stat-value { font-size: 1.5rem; font-weight: bold; }
    .treatment-picker {
        display: flex; gap: 0.75rem; flex-wrap: wrap;
        align-items: center; margin-bottom: 0.5rem;
    }
    .treatment-picker label {
        display: flex; align-items: center; gap: 0.3rem;
        font-size: 0.85rem; margin: 0; white-space: nowrap;
    }
"""


def _treatment_picker_html(
    available: list[str], selected: set[str],
) -> str:
    """Multi-select checkboxes for which treatments to overlay on the chart."""
    boxes = "".join(
        f'<label>'
        f'<input type="checkbox" name="treatments" value="{html.escape(t, quote=True)}"'
        f'{" checked" if t in selected else ""} onchange="this.form.submit()">'
        f'{html.escape(t)}'
        f"</label>"
        for t in available
    )
    return f"""
        <article style="padding:0.5rem 1rem;">
            <form method="get" class="treatment-picker">
                {boxes}
            </form>
        </article>
    """


def _update_button_html() -> str:
    return """
        <form method="post" action="/sensor-monitor/soil/forecast/train"
              style="margin-bottom:0.5rem;">
            <button type="submit" style="width:100%;">Update</button>
        </form>
    """


def _status_banner_html(trained: str | None, msg: str | None) -> str:
    if trained == "ok":
        return '<article class="success"><strong>Model updated.</strong></article>'
    if trained == "error":
        detail = f" {html.escape(msg)}" if msg else ""
        return f'<article class="warning"><strong>Update failed.</strong>{detail}</article>'
    return ""


def _scan_models() -> list[Path]:
    if not _MODELS_DIR.exists():
        return []
    return sorted(_MODELS_DIR.glob("*.pkl"))


def _load_models(pkl_paths: list[Path]) -> dict[tuple[str, str], SoilForecaster]:
    result: dict[tuple[str, str], SoilForecaster] = {}
    for path in pkl_paths:
        try:
            fc = SoilForecaster.load(path)
            result[(fc.sensor_type, fc.treatment)] = fc
        except Exception as exc:
            print(f"[soil_forecast] failed to load model {path}: {exc}")
    return result


def _build_series_map(df: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    """Produce daily-median series per (sensor_type, treatment) from raw fetch."""
    treatment_map = load_device_treatment_map()
    d = df.copy()
    d["treatment"] = d["device"].map(treatment_map)
    d = d.dropna(subset=["treatment"])
    d["date"] = d["time"].dt.normalize()

    series_map: dict[tuple[str, str], pd.Series] = {}
    for (sensor, treatment), g in d.groupby(["sensor", "treatment"]):
        daily = g.groupby("date")["value"].median()
        daily.index = pd.to_datetime(daily.index)
        series_map[(str(sensor), str(treatment))] = daily
    return series_map


def _run_predictions(
    forecasters: dict[tuple[str, str], SoilForecaster],
    series_map: dict[tuple[str, str], pd.Series],
) -> dict[tuple[str, str], dict[int, float] | str]:
    results: dict[tuple[str, str], dict[int, float] | str] = {}
    for key, fc in forecasters.items():
        series = series_map.get(key)
        if series is None or series.empty:
            results[key] = "no recent data"
            continue
        try:
            results[key] = fc.predict(series)
        except ValueError as e:
            results[key] = str(e)
        except Exception as e:
            results[key] = f"error: {e}"
    return results


def _build_forecast_chart(
    series_map: dict[tuple[str, str], pd.Series],
    predictions: dict[tuple[str, str], dict[int, float] | str],
    forecasters: dict[tuple[str, str], SoilForecaster],
    selected_treatments: set[str],
) -> str:
    """Two-panel chart: history (solid) + forecast bridge (dashed) per treatment.

    The shaded band around each forecast point is +/- that horizon's
    validation MAE, giving a visual sense of how trustworthy each forecast is.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
        subplot_titles=tuple(
            f"{_SENSOR_META[sensor][0]} ({_SENSOR_META[sensor][1]})"
            for sensor, _ in _SENSOR_ROWS
        ),
    )
    row_by_sensor = dict(_SENSOR_ROWS)

    seen_treatments: set[str] = set()

    for (sensor_type, treatment), series in sorted(series_map.items()):
        if treatment not in selected_treatments:
            continue
        row = row_by_sensor.get(sensor_type)
        if row is None or series.empty:
            continue

        color = treatment_color(treatment)
        show = treatment not in seen_treatments
        if show:
            seen_treatments.add(treatment)

        fig.add_trace(
            go.Scatter(
                x=series.index, y=series.values,
                name=treatment, mode="lines",
                line={"color": color, "width": 2},
                legendgroup=treatment, showlegend=show,
                hovertemplate=(
                    f"<b>{treatment}</b><br>%{{x}}<br>%{{y:.2f}}<extra></extra>"
                ),
            ),
            row=row, col=1,
        )

        result = predictions.get((sensor_type, treatment))
        if not isinstance(result, dict) or not result:
            continue

        last_date = series.index[-1]
        last_value = float(series.iloc[-1])
        horizons = sorted(result)
        bridge_x = [last_date] + [
            last_date + pd.Timedelta(days=h) for h in horizons
        ]
        bridge_y = [last_value] + [result[h] for h in horizons]

        fig.add_trace(
            go.Scatter(
                x=bridge_x, y=bridge_y,
                name=treatment, mode="lines+markers",
                line={"color": color, "width": 2, "dash": "dash"},
                marker={"symbol": "diamond", "size": 6},
                legendgroup=treatment, showlegend=False,
                hovertemplate=(
                    f"<b>{treatment} (forecast)</b><br>"
                    "%{x}<br>%{y:.2f}<extra></extra>"
                ),
            ),
            row=row, col=1,
        )

        fc = forecasters.get((sensor_type, treatment))
        mae_by_horizon: dict[int, float] = {}
        if fc is not None:
            summary = fc.summary()
            mae_by_horizon = dict(
                zip(summary["horizon_days"], summary["val_mae"], strict=False)
            )

        # Only shade horizons that actually have a validation MAE. Filling a
        # missing MAE with 0.0 would draw a width-0 band that reads as
        # "perfectly certain" — worse than showing no band at all.
        band_horizons = [h for h in horizons if mae_by_horizon.get(h) is not None]
        if band_horizons:
            band_x = [last_date] + [
                last_date + pd.Timedelta(days=h) for h in band_horizons
            ]
            band_upper = [last_value] + [
                result[h] + mae_by_horizon[h] for h in band_horizons
            ]
            band_lower = [last_value] + [
                result[h] - mae_by_horizon[h] for h in band_horizons
            ]
            fig.add_trace(
                go.Scatter(
                    x=band_x + band_x[::-1],
                    y=band_upper + band_lower[::-1],
                    fill="toself", fillcolor=color, opacity=0.15,
                    line={"width": 0}, hoverinfo="skip",
                    legendgroup=treatment, showlegend=False,
                ),
                row=row, col=1,
            )

    for sensor_type, row in _SENSOR_ROWS:
        fig.update_yaxes(title_text=_SENSOR_META[sensor_type][1], row=row, col=1)
    fig.update_xaxes(showticklabels=True, tickformat="%d %b", tickangle=-30)

    fig.update_layout(
        template="plotly_white",
        height=700,
        hovermode="x unified",
        legend={"orientation": "v", "yanchor": "top", "y": 1,
                "xanchor": "left", "x": 1.02},
        margin={"r": 140},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")


@router.get("/soil/forecast", response_class=HTMLResponse)
async def soil_forecast(
    request: Request,
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    treatments: Annotated[
        list[str] | None, Query(description="Treatments to overlay on the chart"),
    ] = None,
    trained: Annotated[str | None, Query()] = None,
    msg: Annotated[str | None, Query()] = None,
) -> str:
    """Daily soil temperature and moisture forecast (day+1..7) per treatment."""
    status_banner = _status_banner_html(trained, msg)
    # Retraining is admin-only (see the POST route). Hide the Update button from
    # non-admins so the action isn't exposed — mirrors red's DLI model card.
    update_button = _update_button_html() if is_admin(request) else ""
    pkl_paths = _scan_models()

    if not pkl_paths:
        content = f"""
            <h1>Soil Forecast</h1>
            {status_banner}
            {update_button}
            <article>
              <p>No forecast models found in <code>{_MODELS_DIR}</code> yet.</p>
            </article>
        """
        return render_page(
            PAGE_TITLE,
            content,
            show_back_link=True,
            back_url="/sensor-monitor",
            data_source=provider.data_source_label,
            extra_css=FORECAST_CSS,
        )

    forecasters = _load_models(pkl_paths)

    now = datetime.now(UTC)
    start_dt = now - timedelta(days=_RECENT_DAYS)

    try:
        df = await provider.fetch_data(
            sensor_tags=_FORECAST_SENSORS,
            start=start_dt,
            end=now,
        )
    except Exception:
        logger.exception("Soil forecast: failed to fetch recent data")
        return render_page(
            PAGE_TITLE,
            "<h1>Soil Forecast</h1><p>Error fetching recent data.</p>",
            show_back_link=True,
            back_url="/sensor-monitor",
            data_source=provider.data_source_label,
            extra_css=FORECAST_CSS,
        )

    if df.empty:
        return render_page(
            PAGE_TITLE,
            "<h1>Soil Forecast</h1>"
            "<p>No recent sensor data available for prediction.</p>",
            show_back_link=True,
            back_url="/sensor-monitor",
            data_source=provider.data_source_label,
            extra_css=FORECAST_CSS,
        )

    series_map = _build_series_map(df)
    predictions = _run_predictions(forecasters, series_map)

    all_keys = list(series_map) + list(forecasters)
    available_treatments = sorted({t for _, t in all_keys})
    if treatments:
        selected = {t for t in treatments if t in available_treatments}
    elif _DEFAULT_TREATMENT in available_treatments:
        selected = {_DEFAULT_TREATMENT}
    else:
        selected = set(available_treatments[:1])

    picker_html = _treatment_picker_html(available_treatments, selected)
    chart_html = _build_forecast_chart(series_map, predictions, forecasters, selected)

    trained_ats = [
        t for fc in forecasters.values()
        if (t := getattr(fc, "trained_at", None)) is not None
    ]
    last_trained = (
        f"models last trained {max(trained_ats).strftime('%Y-%m-%d %H:%M UTC')}"
        if trained_ats else "model training date unknown"
    )

    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    content = f"""
        <h1>Soil Forecast</h1>
        {status_banner}
        {update_button}
        <p style="font-size:0.8rem;opacity:0.7;margin-top:-0.5rem">
            Ridge regression per treatment &mdash; generated {generated_at}
            &mdash; {last_trained}
        </p>
        {picker_html}
        {render_card(
            "History &amp; forecast (dashed = next 7 days, "
            "shaded = validation MAE)",
            chart_html,
        )}
    """
    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True,
        back_url="/sensor-monitor",
        data_source=provider.data_source_label,
        extra_css=FORECAST_CSS,
    )


async def _train_from_readings(readings: pd.DataFrame) -> dict:
    """Map devices→treatments and fit+save every (sensor, treatment) model.

    Shared by the admin Update route and the startup bootstrap so both prepare
    and write models identically. Returns the {(sensor, treatment):
    SoilForecaster} map (empty if no treatment had enough growing-season data).
    """
    treatment_map = load_device_treatment_map()
    df = readings.copy()
    df["treatment"] = df["device"].map(treatment_map)
    df = df.dropna(subset=["treatment"])
    train_df = df.rename(columns={"time": "timestamp", "sensor": "sensor_type"})
    # train_all_forecasters is CPU-bound (numpy) — run it off the event loop so
    # a retrain doesn't block every other request while it fits.
    return await run_in_threadpool(
        train_all_forecasters, train_df, output_dir=str(_MODELS_DIR),
    )


async def bootstrap_models_if_missing(provider: SensorDataProvider) -> None:
    """Train soil models on startup when none exist on disk.

    Models live on ephemeral container storage (see `_MODELS_DIR`), so a restart
    wipes them. Mirroring red's DLI model, the dashboard retrains on boot from
    the DB rather than persisting to a PVC. No-op when models are already present
    or a manual retrain is already running. Never raises — a failure here must
    not take down startup; the admin Update button remains a fallback.
    """
    if _scan_models():
        logger.info("Soil forecast: models already on disk, skipping boot training")
        return
    if _training_lock.locked():
        return
    async with _training_lock:
        try:
            df = await provider.fetch_data(sensor_tags=_FORECAST_SENSORS)
            if df.empty:
                logger.warning("Soil forecast boot training: no sensor data available")
                return
            forecasters = await _train_from_readings(df)
            logger.info(
                "Soil forecast boot training: %d model(s) trained", len(forecasters),
            )
        except Exception:
            logger.exception("Soil forecast boot training failed")


@router.post(
    "/soil/forecast/train",
    dependencies=[Depends(verify_session_admin)],
)
async def soil_forecast_train(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> RedirectResponse:
    """Fit (or refit) every (sensor, treatment) soil forecast model.

    Admin-only (see the router dependency): retraining rewrites the on-disk
    models and hits the DB, so it's gated like red's DLI model train route.

    Fetches all available soil temperature/moisture history — no date range —
    since `train_all_forecasters` itself restricts training to growing-season
    (Mar-Oct) months across whatever years are present. Redirects straight
    back to the forecast page (POST-redirect-GET) with a status banner rather
    than rendering its own results page.
    """
    back_url = "/sensor-monitor/soil/forecast"

    def _failed(message: str) -> RedirectResponse:
        return RedirectResponse(
            f"{back_url}?trained=error&msg={quote(message)}", status_code=303,
        )

    if _training_lock.locked():
        return _failed("Training is already in progress — try again shortly.")

    async with _training_lock:
        try:
            df = await provider.fetch_data(sensor_tags=_FORECAST_SENSORS)
        except Exception:
            logger.exception("Soil forecast training: failed to fetch data")
            return _failed("Could not fetch sensor data.")

        if df.empty:
            return _failed("No soil sensor data available.")

        try:
            forecasters = await _train_from_readings(df)
        except Exception:
            logger.exception("Soil forecast training: model fitting failed")
            return _failed("Model training failed unexpectedly.")

    if not forecasters:
        return _failed(
            "No treatment had enough growing-season data to train a model "
            "(need at least 60 days of Mar-Oct history).",
        )

    return RedirectResponse(f"{back_url}?trained=ok", status_code=303)
