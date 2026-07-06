"""GET /dli/model — View model status and training options."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.red.dli import (
    DEFAULT_TRAINING_START,
    NATURAL_LIGHT_SENSOR,
    WEATHER_STATION_SENSOR,
    get_model,
)
from wp6_data.shared import render_page, render_stat_grid, render_table

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI Model Status"


@router.get("/", response_class=HTMLResponse)
async def dli_model_status() -> str:
    """View model status and training options."""
    model = get_model()

    if model.is_trained() and model.stats:
        stats = model.stats
        s1 = stats.stage1
        s2 = stats.stage2

        # Show feature names if available
        s1_features = getattr(s1, "feature_names", list(s1.coefficients.keys()))
        s2_features = getattr(s2, "feature_names", list(s2.coefficients.keys()))

        # Intercept row first, then per-feature coefficients.
        s1_coef_table = render_table(
            ["Feature", "Coefficient"],
            [["Intercept", f"{s1.intercept:+.4f}"]]
            + [[name, f"{s1.coefficients.get(name, 0):+.4f}"] for name in s1_features],
            sortable=False,
        )
        s2_coef_table = render_table(
            ["Feature", "Coefficient"],
            [["Intercept", f"{s2.intercept:+.4f}"]]
            + [[name, f"{s2.coefficients.get(name, 0):+.4f}"] for name in s2_features],
            sortable=False,
        )

        # Model version info
        model_version = getattr(stats, "model_version", 4)
        model_type = "Ridge regression" if model_version >= 5 else "Linear regression"

        stats_grid = render_stat_grid([
            (f"{stats.r2_score:.3f}", "Combined R²"),
            (f"{s1.r2_score:.3f}", "Stage 1 R²"),
            (f"{s2.r2_score:.3f}", "Stage 2 R²"),
            (f"{stats.n_samples:,}", "Days"),
            (f"{getattr(stats, 'attenuation_factor', 1.0):.3f}", "Attenuation"),
        ], cols=5)

        status_html = f"""
            <article>
                <h3 class="success">Two-Stage Model Trained (Daily)</h3>
                <p>
                    OpenMeteo weather → {WEATHER_STATION_SENSOR} daily lux
                    → indoor PAR ({model_type})
                </p>

                {stats_grid}

                <h4>Stage 1: Weather API → Local Lux (Daily)</h4>
                     <p>Calibrates OpenMeteo weather to {WEATHER_STATION_SENSOR} daily lux sum
                   (R²={s1.r2_score:.3f}, RMSE={s1.rmse:.0f} lux/day)</p>
                <small>Features: {', '.join(s1_features)}</small>
                {s1_coef_table}

                <h4>Stage 2: Outdoor Lux → Indoor PAR (Daily)</h4>
                <p>Greenhouse transmission model for daily totals
                   (R²={s2.r2_score:.3f}, RMSE={s2.rmse:.1f} μmol/m²/day)</p>
                <small>Features: {', '.join(s2_features)}</small>
                {s2_coef_table}

                <small>
                    Outdoor sensor: <strong>{stats.outdoor_sensor}</strong><br>
                    Indoor sensor: <strong>{stats.indoor_sensor}</strong><br>
                    Attenuation: <strong>{getattr(stats, 'attenuation_factor', 1.0):.4f}</strong>
                    ({getattr(stats, 'attenuation_samples', 0)} days)<br>
                    Trained: {stats.training_date.strftime('%Y-%m-%d %H:%M')} UTC<br>
                    Data range: {stats.date_range[0]} to {stats.date_range[1]}<br>
                    Model version: v{model_version}
                </small>
            </article>
        """
    else:
        status_html = f"""
            <article>
                <h3 class="warning">No Model Trained</h3>
                <p>The two-stage PAR prediction model has not been trained yet.</p>
                <p>Training requires:</p>
                <ul>
                    <li>
                        <strong>Stage 1</strong>: OpenMeteo weather data +
                        {WEATHER_STATION_SENSOR} lux readings
                    </li>
                    <li>
                        <strong>Stage 2</strong>: {WEATHER_STATION_SENSOR} lux +
                        {NATURAL_LIGHT_SENSOR} indoor readings
                    </li>
                </ul>
            </article>
        """

    train_form = f"""
        <article>
            <h3>Train Model</h3>
            <p>Trains a two-stage model:</p>
            <ol>
                <li>
                    <strong>Stage 1</strong>: OpenMeteo → {WEATHER_STATION_SENSOR} lux
                    (weather API calibration)
                </li>
                <li>
                    <strong>Stage 2</strong>: {WEATHER_STATION_SENSOR} lux → indoor PAR
                    (greenhouse transmission)
                </li>
            </ol>
            <form method="post" action="/dli/model/train">
                <button type="submit">Train Model</button>
            </form>
            <small>
                Uses all data from {WEATHER_STATION_SENSOR} and {NATURAL_LIGHT_SENSOR}
                since {DEFAULT_TRAINING_START.isoformat()}.
            </small>
        </article>
    """

    content = f"""
        <h1>Light Prediction Model</h1>
        <p>Two-stage ML model: OpenMeteo forecast → local calibration → indoor PAR prediction.</p>
        {status_html}
        {train_form}
        <p>
            <a href="/dli/model/diagnostic">View training diagnostic</a> -
            investigate data alignment and correlation issues.
        </p>
    """

    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True, back_url="/dli",
    )
