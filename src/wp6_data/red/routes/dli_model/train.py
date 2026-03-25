"""POST /dli/model/train — Train the two-stage light prediction model."""

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection
from wp6_data.red.dli import (
    DEFAULT_TRAINING_START,
    NATURAL_LIGHT_SENSOR,
    TOTAL_LIGHT_SENSOR,
    WEATHER_STATION_SENSOR,
    ModelStats,
    OpenMeteoClient,
    get_model,
)
from wp6_data.shared import render_page

router = APIRouter()


async def train_model_from_db(db: MySQLConnection, weather_client: OpenMeteoClient) -> ModelStats:
    """Train the two-stage light prediction model from database data.

    Fetches sensor data and weather data, trains the model, and saves it.
    Returns ModelStats on success, raises on failure.
    """
    start_dt = datetime(
        DEFAULT_TRAINING_START.year,
        DEFAULT_TRAINING_START.month,
        DEFAULT_TRAINING_START.day,
        tzinfo=UTC,
    )
    end_dt = datetime.now(UTC)

    above_lamp_df = await db.get_par_readings(
        device_ids=[NATURAL_LIGHT_SENSOR], start=start_dt, end=end_dt
    )
    plant_level_df = await db.get_par_readings(
        device_ids=[TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
    )

    if above_lamp_df.empty:
        raise ValueError(f"No indoor PAR data ({NATURAL_LIGHT_SENSOR}) found for training")

    indoor_df = above_lamp_df

    outdoor_df = await db.get_weather_station_readings(start=start_dt, end=end_dt)
    if outdoor_df.empty:
        raise ValueError(f"No weather station data ({WEATHER_STATION_SENSOR}) found for training")

    weather_df = await weather_client.get_historical_dataframe_multi(
        start_dt.date(),
        end_dt.date(),
        radiation_var="direct_radiation",
        include_diffuse=True,
    )
    if weather_df.empty:
        raise ValueError("No OpenMeteo weather data found for training")

    model = get_model()
    stats = model.train(
        weather_df=weather_df,
        outdoor_df=outdoor_df,
        indoor_df=indoor_df,
        indoor_sensor=NATURAL_LIGHT_SENSOR,
        plant_level_df=plant_level_df if not plant_level_df.empty else None,
        above_lamp_df=above_lamp_df,
    )
    model.save()
    return stats

PAGE_TITLE = "SPoHF Red - Train DLI Model"

@router.post("/train", response_class=HTMLResponse)
async def dli_model_train() -> str:
    """Train the two-stage light prediction model."""
    if not deps.db:
        return render_page(
            PAGE_TITLE,
            "<h1>Database not connected</h1>",
            show_back_link=True, back_url="/dli/model",
        )

    try:
        stats = await train_model_from_db(deps.db, deps.get_weather_client())
    except Exception as e:
        return render_page(
            PAGE_TITLE,
            f"<h1>Training Failed</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    content = f"""
        <article style="border: 2px solid var(--pico-ins-color, green)">
            <h1>Two-Stage Model Trained (Daily)</h1>
            <div class="stats-grid cols-5">
                <article>
                    <div class="stat-value">{stats.r2_score:.3f}</div>
                    <small>Combined R²</small>
                </article>
                <article>
                    <div class="stat-value">{stats.stage1.r2_score:.3f}</div>
                    <small>Stage 1 R²</small>
                </article>
                <article>
                    <div class="stat-value">{stats.stage2.r2_score:.3f}</div>
                    <small>Stage 2 R²</small>
                </article>
                <article>
                    <div class="stat-value">{stats.n_samples:,}</div>
                    <small>Days</small>
                </article>
                <article>
                    <div class="stat-value">{stats.attenuation_factor:.3f}</div>
                    <small>Attenuation</small>
                </article>
            </div>
                <p>
                     <strong>Stage 1</strong>: OpenMeteo daily direct_radiation
                     → {WEATHER_STATION_SENSOR} daily lux
                </p>
                <p><strong>Stage 2</strong>: {WEATHER_STATION_SENSOR} daily lux
                    → {NATURAL_LIGHT_SENSOR} (above-lamp)
               → ×{stats.attenuation_factor:.3f} → plant-level estimate</p>
            <p>
                Model saved and will be used for PAR predictions.
                <a href="/dli/model">View full model details</a>
            </p>
        </article>
    """

    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True, back_url="/dli/model",
    )
