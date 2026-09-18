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


def _verdict(stage) -> str:
    """One stage's out-of-sample verdict, or a note that it has none.

    In-sample R² is kept alongside rather than hidden, because the gap between
    the two is itself the diagnosis: a stage that fits well and generalises
    badly is overfitting, and one that does neither is missing a feature.
    """
    if getattr(stage, "holdout_r2", None) is None:
        return (
            '<p class="warning">No out-of-fold score on this artifact — '
            "retrain to measure the stage.</p>"
        )
    skills = ", ".join(
        f"vs {name} <strong>{value:+.3f}</strong>"
        for name, value in sorted(stage.skill.items())
    )
    beaten = sorted(name for name, value in stage.skill.items() if value <= 0)
    note = (
        f'<br><span class="warning">Beaten by {", ".join(beaten)} — this stage '
        "is not earning its place.</span>"
        if beaten
        else ""
    )
    return (
        f"<p>Out-of-fold R² <strong>{stage.holdout_r2:.3f}</strong> over "
        f"{stage.n_holdout} held-out days (RMSE {stage.holdout_rmse:,.0f}). "
        f"Skill {skills}.{note}</p>"
    )


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

        # The headline is the chain measured end to end, not the product of two
        # in-sample R² — see ModelStats.r2_score.
        chain = getattr(stats, "chain", None)
        measured = chain if chain is not None and chain.holdout_r2 is not None else None
        skill_tiles = [
            (f"{measured.skill[name]:+.3f}", f"Skill vs {name}")
            for name in ("persistence", "climatology")
            if measured is not None and name in measured.skill
        ]
        stats_grid = render_stat_grid([
            (
                f"{stats.r2_score:.3f}",
                "Chain R²",
                "out-of-fold" if measured else "in-sample product",
            ),
            *skill_tiles,
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
                   (in-sample R²={s1.r2_score:.3f}, RMSE={s1.rmse:.0f} lux/day)</p>
                {_verdict(s1)}
                <small>Features: {', '.join(s1_features)}</small>
                {s1_coef_table}

                <h4>Stage 2: Outdoor Lux → Indoor PAR (Daily)</h4>
                <p>Greenhouse transmission model for daily totals
                   (in-sample R²={s2.r2_score:.3f}, RMSE={s2.rmse:.1f} μmol/m²/day)</p>
                {_verdict(s2)}
                <small>Features: {', '.join(s2_features)}</small>
                {s2_coef_table}

                <h4>The chain, end to end</h4>
                <p>Stage 2 is fitted on the lux the station recorded, but served
                   the lux stage 1 predicts &mdash; so this is the chain scored the
                   way it actually runs.</p>
                {_verdict(chain) if chain is not None else
                 '<p class="warning">Not scored end to end on this artifact.</p>'}

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
