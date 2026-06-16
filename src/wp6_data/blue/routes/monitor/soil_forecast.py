"""GET /sensor-monitor/soil/forecast — 7-day and 30-day soil condition forecasts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.blue.routes.monitor._treatment import load_device_treatment_map
from wp6_data.blue.soil_forecaster import SoilForecaster
from wp6_data.config import Settings
from wp6_data.shared import render_card, render_page
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Soil Forecast"

_FORECAST_SENSORS = ["soilTemperature", "soilMoisture"]
_SENSOR_META: dict[str, tuple[str, str]] = {
    "soilTemperature": ("Soil Temperature", "°C"),
    "soilMoisture":    ("Soil Moisture",    "%VWC"),
}
_RECENT_DAYS = 30  # days of history needed for lag features

_settings = Settings()
_MODELS_DIR = Path(_settings.blue_export_dir) / "models"

FORECAST_CSS = """
    .stats-grid { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .stats-grid article {
        flex: 1; min-width: 110px; text-align: center; padding: 0.5rem;
    }
    .stat-value { font-size: 1.5rem; font-weight: bold; }
"""


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
        except Exception:
            pass
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
            results[key] = f"needs exog: {e}"
        except Exception as e:
            results[key] = f"error: {e}"
    return results


def _stats_grid_html(
    results: dict[tuple[str, str], dict[int, float] | str],
    sensor_type: str,
    horizon: int,
    unit: str,
) -> str:
    """Render a GDD-style stat grid for one sensor type × horizon."""
    items: list[str] = []
    for (st, treatment), result in sorted(results.items()):
        if st != sensor_type:
            continue
        if isinstance(result, dict) and horizon in result:
            value_html = f"{result[horizon]:.1f}&thinsp;{unit}"
            dim = ""
        else:
            value_html = "—"
            dim = ' style="color:#9ca3af;"'
        items.append(
            f'<article>'
            f'<div class="stat-value"{dim}>{value_html}</div>'
            f"<small>{treatment}</small>"
            f"</article>"
        )
    if not items:
        return "<p>No models available for this sensor type.</p>"
    return f'<div class="stats-grid">{"".join(items)}</div>'


def _details_table_html(
    results: dict[tuple[str, str], dict[int, float] | str],
    horizons: list[int],
) -> str:
    """Render a full table with all sensor types and forecast horizons."""
    temp_headers = "".join(
        f"<th>Temp {h}d (°C)</th>" for h in horizons
    )
    moist_headers = "".join(
        f"<th>Moisture {h}d (%VWC)</th>" for h in horizons
    )
    header = (
        f"<tr><th>Treatment</th>{temp_headers}{moist_headers}</tr>"
    )

    treatments = sorted({t for _, t in results})
    rows: list[str] = []
    for treatment in treatments:
        temp_cells = ""
        moist_cells = ""
        for horizon in horizons:
            t_res = results.get(("soilTemperature", treatment))
            if isinstance(t_res, dict):
                temp_cells += f"<td>{t_res.get(horizon, '—')}</td>"
            else:
                note = t_res or "—"
                temp_cells += f'<td><em style="color:#9ca3af;">{note}</em></td>'

            m_res = results.get(("soilMoisture", treatment))
            if isinstance(m_res, dict):
                moist_cells += f"<td>{m_res.get(horizon, '—')}</td>"
            else:
                note = m_res or "—"
                moist_cells += f'<td><em style="color:#9ca3af;">{note}</em></td>'

        rows.append(
            f"<tr><td><strong>{treatment}</strong></td>"
            f"{temp_cells}{moist_cells}</tr>"
        )

    body = "".join(rows)
    return f"<table><thead>{header}</thead><tbody>{body}</tbody></table>"


@router.get("/soil/forecast", response_class=HTMLResponse)
async def soil_forecast(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """7-day and 30-day soil temperature and moisture forecasts per treatment."""
    pkl_paths = _scan_models()

    if not pkl_paths:
        content = f"""
            <h1>Soil Forecast</h1>
            <article>
              <p>No forecast models found in <code>{_MODELS_DIR}</code>.</p>
              <p>Train models using the <code>soil_forecaster</code> module and save
                 the <code>.pkl</code> files to that directory.</p>
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
    except Exception as e:
        return render_page(
            PAGE_TITLE,
            f"<h1>Soil Forecast</h1><p>Error fetching recent data: {e}</p>",
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

    all_horizons = sorted({
        h
        for r in predictions.values()
        if isinstance(r, dict)
        for h in r
    }) or [7, 30]

    primary_horizon = all_horizons[0]  # typically 7

    temp_stats = _stats_grid_html(predictions, "soilTemperature", primary_horizon, "°C")
    moist_stats = _stats_grid_html(predictions, "soilMoisture", primary_horizon, "%VWC")
    details = _details_table_html(predictions, all_horizons)

    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    content = f"""
        <h1>Soil Forecast</h1>
        <p style="font-size:0.8rem;opacity:0.7;margin-top:-0.5rem">
            Ridge regression &mdash; trained on 2025 growing season
            (March&ndash;October) &mdash; {generated_at}
        </p>
        {render_card(f"Soil Temperature &mdash; {primary_horizon}-day forecast (°C)", temp_stats)}
        {render_card(f"Soil Moisture &mdash; {primary_horizon}-day forecast (%VWC)", moist_stats)}
        {render_card("All Horizons", details)}
    """
    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True,
        back_url="/sensor-monitor",
        data_source=provider.data_source_label,
        extra_css=FORECAST_CSS,
    )
