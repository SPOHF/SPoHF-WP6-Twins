"""Red dashboard DLI model endpoints: status, train, diagnostic."""

from datetime import UTC, datetime

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Depends
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
    derive_daily_lamp_profile,
    get_model,
    subtract_lamp_from_sensor,
)
from wp6_data.shared import render_page

router = APIRouter(prefix="/dli/model")


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


@router.get("", response_class=HTMLResponse)
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


@router.post("/train", response_class=HTMLResponse)
async def dli_model_train(user: str = Depends(deps.verify_admin_auth)) -> str:
    """Train the two-stage light prediction model."""
    if not deps.db:
        return render_page(
            "Train Model - WP6 Red",
            "<h1>Database not connected</h1>",
            show_back_link=True, back_url="/dli/model",
        )

    try:
        stats = await train_model_from_db(deps.db, deps.get_weather_client())
    except Exception as e:
        return render_page(
            "Train Model - WP6 Red",
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
        "Model Trained - WP6 Red",
        content,
        show_back_link=True, back_url="/dli/model",
    )


@router.get("/diagnostic", response_class=HTMLResponse)
async def dli_model_diagnostic(
    user: str = Depends(deps.verify_admin_auth),
) -> str:
    """Diagnostic view to investigate model training data."""
    if not deps.db:
        return render_page(
            "Model Diagnostic - WP6 Red",
            "<h1>Database not connected</h1>",
            show_back_link=True, back_url="/dli/model",
        )

    # Use same date range as training
    start_dt = datetime(
        DEFAULT_TRAINING_START.year,
        DEFAULT_TRAINING_START.month,
        DEFAULT_TRAINING_START.day,
        tzinfo=UTC,
    )
    end_dt = datetime.now(UTC)

    # Fetch sensor data (no weather API call needed)
    try:
        indoor_df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        plant_level_df = await deps.db.get_par_readings(
            device_ids=[TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        outdoor_df = await deps.db.get_weather_station_readings(start=start_dt, end=end_dt)
    except Exception as e:
        return render_page(
            "Model Diagnostic - WP6 Red",
            f"<h1>Error fetching data</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    # --- Section 1: Raw Data Counts ---
    def date_range_str(df, time_col="time"):
        if df.empty:
            return "No data"
        dates = pd.to_datetime(df[time_col], utc=True)
        return f"{dates.min().date()} to {dates.max().date()}"

    counts_html = f"""
        <article>
            <h3>Raw Data Counts</h3>
            <div class="stats-grid">
                <article>
                    <div class="stat-value">{len(indoor_df):,}</div>
                    <small>Above-lamp PAR ({NATURAL_LIGHT_SENSOR})</small>
                </article>
                <article>
                    <div class="stat-value">{len(plant_level_df):,}</div>
                    <small>Plant-level PAR ({TOTAL_LIGHT_SENSOR})</small>
                </article>
                <article>
                    <div class="stat-value">{len(outdoor_df):,}</div>
                    <small>{WEATHER_STATION_SENSOR} readings</small>
                </article>
            </div>
            <small>
                Above-lamp: {date_range_str(indoor_df)}<br>
                Plant-level: {date_range_str(plant_level_df)}<br>
                Outdoor: {date_range_str(outdoor_df)}
            </small>
        </article>
    """

    # --- Sections 2 & 3: Lamp Profile + Attenuation Ratio ---
    lamp_html = ""
    ratio_html = ""

    if not indoor_df.empty and not plant_level_df.empty:
        lamp_profile = derive_daily_lamp_profile(indoor_df, plant_level_df)

        # Section 2: Lamp Profile Summary
        if not lamp_profile.empty:
            days_with_lamp = int(lamp_profile["lamp_power_par"].notna().sum())
            total_profile_days = len(lamp_profile)
            lamp_powers = lamp_profile["lamp_power_par"].dropna()
            median_lamp_power = float(lamp_powers.median()) if len(lamp_powers) > 0 else 0.0

            lamp_days = lamp_profile.dropna(subset=["lamp_start", "lamp_end"])
            if not lamp_days.empty:
                lamp_hours = lamp_days.apply(
                    lambda r: (r["lamp_end"] - r["lamp_start"] + 1)
                    if r["lamp_start"] <= r["lamp_end"]
                    else (24 - r["lamp_start"] + r["lamp_end"] + 1),
                    axis=1,
                )
                avg_lamp_hours = float(lamp_hours.mean())
            else:
                avg_lamp_hours = 0.0

            lamp_html = f"""
                <article>
                    <h3>Lamp Profile Summary</h3>
                    <p>Derived from {NATURAL_LIGHT_SENSOR} (above lamp) and
                       {TOTAL_LIGHT_SENSOR} (plant level)</p>
                    <div class="stats-grid">
                        <article>
                            <div class="stat-value">{days_with_lamp}/{total_profile_days}</div>
                            <small>Days with lamp detected</small>
                        </article>
                        <article>
                            <div class="stat-value">{median_lamp_power:.0f}</div>
                            <small>Median lamp PAR (μmol/m²/s)</small>
                        </article>
                        <article>
                            <div class="stat-value">{avg_lamp_hours:.1f}h</div>
                            <small>Avg lamp schedule</small>
                        </article>
                    </div>
                </article>
            """
        else:
            lamp_html = """
                <article>
                    <h3>Lamp Profile Summary</h3>
                    <small>No overlapping days between sensors
                       for lamp profile derivation.</small>
                </article>
            """

        # Section 3: Attenuation Ratio time series
        if not lamp_profile.empty and lamp_profile["lamp_power_par"].notna().any():
            above = indoor_df.copy()
            above["time"] = pd.to_datetime(above["time"], utc=True)
            above["date"] = above["time"].dt.date
            above_daily = above.groupby("date").agg({"value": "sum"}).reset_index()
            above_daily.columns = ["date", "above_par_sum"]

            corrected_df = subtract_lamp_from_sensor(plant_level_df, lamp_profile)
            corr_plant = corrected_df.copy()
            corr_plant["time"] = pd.to_datetime(corr_plant["time"], utc=True)
            corr_plant["date"] = corr_plant["time"].dt.date
            corr_plant_daily = (
                corr_plant.groupby("date").agg({"value": "sum"}).reset_index()
            )
            corr_plant_daily.columns = ["date", "plant_par_sum"]
            ratio_df = above_daily.merge(corr_plant_daily, on="date", how="inner")
            ratio_df = ratio_df[
                (ratio_df["above_par_sum"] > 0) & (ratio_df["plant_par_sum"] > 0)
            ]

            if not ratio_df.empty and len(ratio_df) >= 2:
                ratio_df["ratio"] = (
                    ratio_df["plant_par_sum"] / ratio_df["above_par_sum"]
                )
                ratio_df["date"] = pd.to_datetime(ratio_df["date"])
                ratio_df = ratio_df.sort_values("date")

                median_ratio = float(ratio_df["ratio"].median())
                min_ratio = float(ratio_df["ratio"].min())
                max_ratio = float(ratio_df["ratio"].max())

                window = min(14, len(ratio_df))
                ratio_df["rolling_median"] = (
                    ratio_df["ratio"].rolling(window, center=True, min_periods=3).median()
                )

                ratio_df["deviation"] = ratio_df["ratio"] - ratio_df["rolling_median"]
                dev_std = float(ratio_df["deviation"].std())
                outlier_mask = ratio_df["deviation"] < -2 * dev_std
                n_outliers = int(outlier_mask.sum())
                clean_n = len(ratio_df) - n_outliers

                fig_ratio = go.Figure()
                clean_df = ratio_df[~outlier_mask]
                outlier_df = ratio_df[outlier_mask]

                fig_ratio.add_trace(go.Scatter(
                    x=clean_df["date"], y=clean_df["ratio"],
                    mode="markers", name="Daily ratio",
                    marker={"color": "#3498db", "size": 6, "opacity": 0.6},
                ))
                if not outlier_df.empty:
                    fig_ratio.add_trace(go.Scatter(
                        x=outlier_df["date"], y=outlier_df["ratio"],
                        mode="markers", name=f"Occlusion ({n_outliers}d)",
                        marker={"color": "#e74c3c", "size": 8, "symbol": "x"},
                    ))
                fig_ratio.add_trace(go.Scatter(
                    x=ratio_df["date"], y=ratio_df["rolling_median"],
                    mode="lines", name=f"Rolling median ({window}d)",
                    line={"color": "#2ecc71", "width": 2},
                ))
                fig_ratio.add_hline(
                    y=median_ratio, line_dash="dot", line_color="#999",
                    annotation_text=f"Global median: {median_ratio:.3f}",
                    annotation_position="top left",
                )
                ratio_title = (
                    "Daily Attenuation Ratio "
                    f"(lamp-corrected {TOTAL_LIGHT_SENSOR} / {NATURAL_LIGHT_SENSOR})"
                )
                fig_ratio.update_layout(
                    title=ratio_title,
                    xaxis_title="",
                    yaxis_title="Ratio (corrected plant / above-lamp)",
                    height=400,
                    legend={"orientation": "h", "yanchor": "bottom", "y": 1.02,
                            "xanchor": "right", "x": 1},
                )
                ratio_chart_html = fig_ratio.to_html(
                    full_html=False, include_plotlyjs="cdn"
                )

                rolling_clean = ratio_df["rolling_median"].dropna()
                if len(rolling_clean) >= 2:
                    trend_min = float(rolling_clean.min())
                    trend_max = float(rolling_clean.max())
                    trend_range = trend_max - trend_min
                    trend_pct = trend_range / median_ratio * 100
                    trend_label = f"{trend_min:.3f} – {trend_max:.3f} ({trend_pct:.0f}% swing)"
                else:
                    trend_label = "-"

                model = get_model()
                model_factor_html = ""
                if model.stats and model.stats.attenuation_factor != 1.0:
                    model_factor_html = f"""
                        <article>
                            <div class="stat-value">{model.stats.attenuation_factor:.3f}</div>
                            <small>Model factor (stored)</small>
                        </article>
                    """

                ratio_html = f"""
                    <article>
                        <h3>Attenuation: s2100-01 → Plant-Level</h3>
                        <small>Ratio of lamp-corrected plant-level to
                           above-lamp daily PAR (natural light only).
                           Rolling median shows seasonal trend.
                           Red crosses = days &gt;2&sigma; below local trend
                           (likely plant occlusion).</small>
                        <div class="stats-grid cols-auto">
                            <article>
                                <div class="stat-value">{median_ratio:.3f}</div>
                                <small>Live median</small>
                            </article>
                            {model_factor_html}
                            <article>
                                <div class="stat-value">{min_ratio:.3f} – {max_ratio:.3f}</div>
                                <small>Range (all days)</small>
                            </article>
                            <article>
                                <div class="stat-value">{trend_label}</div>
                                <small>Rolling median range</small>
                            </article>
                            <article>
                                <div class="stat-value warning">{n_outliers}</div>
                                <small>Occlusion days ({clean_n} clean)</small>
                            </article>
                        </div>
                        {ratio_chart_html}
                    </article>
                """

    else:
        lamp_html = f"""
            <article>
                <h3>Sensor Data</h3>
                <small>Missing sensor data for diagnostics.
                   Need both {NATURAL_LIGHT_SENSOR} and {TOTAL_LIGHT_SENSOR} readings.</small>
            </article>
        """

    content = f"""
        <h1>Model Training Diagnostic</h1>
        {counts_html}
        {lamp_html}
        {ratio_html}
    """

    return render_page(
        "Model Diagnostic - WP6 Red",
        content,
        show_back_link=True, back_url="/dli/model",
    )
