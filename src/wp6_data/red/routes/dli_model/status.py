"""GET /dli/model — View model status and training options."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    DEFAULT_TRAINING_START,
    NATURAL_LIGHT_SENSOR,
    WEATHER_STATION_SENSOR,
    get_model,
)
from wp6_data.shared import render_page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dli_model_status(user: str = Depends(deps.verify_admin_auth)) -> str:
    """View model status and training options."""
    model = get_model()

    if model.is_trained() and model.stats:
        stats = model.stats
        s1 = stats.stage1
        s2 = stats.stage2

        # Show feature names if available
        s1_features = getattr(s1, "feature_names", list(s1.coefficients.keys()))
        s2_features = getattr(s2, "feature_names", list(s2.coefficients.keys()))

        s1_coef_rows = "".join(
            f"<tr><td>{name}</td><td>{s1.coefficients.get(name, 0):+.4f}</td></tr>"
            for name in s1_features
        )
        s2_coef_rows = "".join(
            f"<tr><td>{name}</td><td>{s2.coefficients.get(name, 0):+.4f}</td></tr>"
            for name in s2_features
        )

        # Model version info
        model_version = getattr(stats, "model_version", 4)
        model_type = "Ridge regression" if model_version >= 5 else "Linear regression"

        status_html = f"""
            <article>
                <h3 class="success">Two-Stage Model Trained (Daily)</h3>
                <p>
                    OpenMeteo weather → {WEATHER_STATION_SENSOR} daily lux
                    → indoor PAR ({model_type})
                </p>

                <div class="stats-grid cols-5">
                    <article>
                        <div class="stat-value">{stats.r2_score:.3f}</div>
                        <small>Combined R²</small>
                    </article>
                    <article>
                        <div class="stat-value">{s1.r2_score:.3f}</div>
                        <small>Stage 1 R²</small>
                    </article>
                    <article>
                        <div class="stat-value">{s2.r2_score:.3f}</div>
                        <small>Stage 2 R²</small>
                    </article>
                    <article>
                        <div class="stat-value">{stats.n_samples:,}</div>
                        <small>Days</small>
                    </article>
                    <article>
                        <div class="stat-value">\
{getattr(stats, 'attenuation_factor', 1.0):.3f}</div>
                        <small>Attenuation</small>
                    </article>
                </div>

                <h4>Stage 1: Weather API → Local Lux (Daily)</h4>
                     <p>Calibrates OpenMeteo weather to {WEATHER_STATION_SENSOR} daily lux sum
                   (R²={s1.r2_score:.3f}, RMSE={s1.rmse:.0f} lux/day)</p>
                <small>Features: {', '.join(s1_features)}</small>
                <table>
                    <tr><th>Feature</th><th>Coefficient</th></tr>
                    <tr><td>Intercept</td><td>{s1.intercept:+.4f}</td></tr>
                    {s1_coef_rows}
                </table>

                <h4>Stage 2: Outdoor Lux → Indoor PAR (Daily)</h4>
                <p>Greenhouse transmission model for daily totals
                   (R²={s2.r2_score:.3f}, RMSE={s2.rmse:.1f} μmol/m²/day)</p>
                <small>Features: {', '.join(s2_features)}</small>
                <table>
                    <tr><th>Feature</th><th>Coefficient</th></tr>
                    <tr><td>Intercept</td><td>{s2.intercept:+.4f}</td></tr>
                    {s2_coef_rows}
                </table>

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
        "Light Model - WP6 Red",
        content,
        show_back_link=True, back_url="/dli",
    )
