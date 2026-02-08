"""Red dashboard DLI model endpoints: status, train, diagnostic."""

from datetime import UTC, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    DEFAULT_TRAINING_START,
    NATURAL_LIGHT_SENSOR,
    TOTAL_LIGHT_SENSOR,
    align_outdoor_to_indoor_daily,
    align_weather_outdoor_hourly,
    analyze_reporting_frequency,
    calculate_correlation_comparison,
    derive_daily_lamp_profile,
    get_model,
    subtract_lamp_from_sensor,
)
from wp6_data.shared import render_page

router = APIRouter(prefix="/dli/model")


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
                <p>OpenMeteo weather → s1000 daily lux → indoor PAR ({model_type})</p>

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
                <p>Calibrates OpenMeteo weather to s1000 daily lux sum
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
        status_html = """
            <article>
                <h3 class="warning">No Model Trained</h3>
                <p>The two-stage PAR prediction model has not been trained yet.</p>
                <p>Training requires:</p>
                <ul>
                    <li><strong>Stage 1</strong>: OpenMeteo weather data + s1000 lux readings</li>
                    <li><strong>Stage 2</strong>: s1000 lux + s2100-01-par indoor readings</li>
                </ul>
            </article>
        """

    train_form = """
        <article>
            <h3>Train Model</h3>
            <p>Trains a two-stage model:</p>
            <ol>
                <li><strong>Stage 1</strong>: OpenMeteo → s1000 lux (weather API calibration)</li>
                <li><strong>Stage 2</strong>: s1000 lux → indoor PAR (greenhouse transmission)</li>
            </ol>
            <form method="post" action="/dli/model/train">
                <button type="submit">Train Model</button>
            </form>
            <small>
                Uses all data from s1000 and s2100-01-par since 2025-10-24.
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

    # Use all data since DEFAULT_TRAINING_START (devices up and running)
    start_dt = datetime(
        DEFAULT_TRAINING_START.year,
        DEFAULT_TRAINING_START.month,
        DEFAULT_TRAINING_START.day,
        tzinfo=UTC,
    )
    end_dt = datetime.now(UTC)

    # Fetch PAR data from both sensors for lamp correction
    try:
        above_lamp_df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        plant_level_df = await deps.db.get_par_readings(
            device_ids=[TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
    except Exception as e:
        return render_page(
            "Train Model - WP6 Red",
            f"<h1>Database Error (indoor PAR)</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    if above_lamp_df.empty:
        return render_page(
            "Train Model - WP6 Red",
            "<h1>No Indoor PAR Data</h1>"
            "<p>No s2100-01-par readings found for the selected date range.</p>",
            show_back_link=True, back_url="/dli/model",
        )

    # Stage 2 trains on s2100-01-par (above lamps, clean r=0.911 with s1000)
    indoor_df = above_lamp_df
    indoor_sensor_label = "s2100-01-par"

    # Fetch outdoor weather station data (s1000 lux)
    try:
        outdoor_df = await deps.db.get_weather_station_readings(start=start_dt, end=end_dt)
    except Exception as e:
        return render_page(
            "Train Model - WP6 Red",
            f"<h1>Database Error (s1000)</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    if outdoor_df.empty:
        return render_page(
            "Train Model - WP6 Red",
            "<h1>No Weather Station Data</h1>"
            "<p>No s1000 lux readings found for the selected date range.</p>",
            show_back_link=True, back_url="/dli/model",
        )

    # Fetch OpenMeteo historical weather data (direct + diffuse radiation for better model)
    client = deps.get_weather_client()
    try:
        weather_df = await client.get_historical_dataframe_multi(
            start_dt.date(), end_dt.date(),
            radiation_var="direct_radiation",
            include_diffuse=True,
        )
    except Exception as e:
        return render_page(
            "Train Model - WP6 Red",
            f"<h1>Weather API Error</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    if weather_df.empty:
        return render_page(
            "Train Model - WP6 Red",
            "<h1>No OpenMeteo Data</h1>"
            "<p>Could not fetch weather data for the date range.</p>",
            show_back_link=True, back_url="/dli/model",
        )

    # Train two-stage model
    model = get_model()
    try:
        stats = model.train(
            weather_df=weather_df,
            outdoor_df=outdoor_df,
            indoor_df=indoor_df,
            indoor_sensor=indoor_sensor_label,
            plant_level_df=plant_level_df if not plant_level_df.empty else None,
            above_lamp_df=above_lamp_df,
        )
        model.save()
    except ValueError as e:
        return render_page(
            "Train Model - WP6 Red",
            f"<h1>Training Failed</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )
    except Exception as e:
        return render_page(
            "Train Model - WP6 Red",
            f"<h1>Training Error</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    extra_css = """
        .success-card { border: 2px solid green; border-radius: 8px; padding: 20px;
                       background: #f0fff0; }
    """

    content = f"""
        <div class="success-card">
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
            <p><strong>Stage 1</strong>: OpenMeteo daily direct_radiation → s1000 daily lux</p>
            <p><strong>Stage 2</strong>: s1000 daily lux → s2100-01-par (above-lamp)
               → ×{stats.attenuation_factor:.3f} → plant-level estimate</p>
            <p>
                Model saved and will be used for PAR predictions.
                <a href="/dli/model">View full model details</a>
            </p>
        </div>
    """

    return render_page(
        "Model Trained - WP6 Red",
        content,
        extra_css=extra_css,
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

    # Fetch all data sources
    try:
        indoor_df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        plant_level_df = await deps.db.get_par_readings(
            device_ids=[TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        outdoor_df = await deps.db.get_weather_station_readings(start=start_dt, end=end_dt)

        # Fetch weather with direct_radiation + diffuse (for improved model)
        client = deps.get_weather_client()
        weather_df = await client.get_historical_dataframe_multi(
            start_dt.date(), end_dt.date(),
            radiation_var="direct_radiation",
            include_diffuse=True,
        )
    except Exception as e:
        return render_page(
            "Model Diagnostic - WP6 Red",
            f"<h1>Error fetching data</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    # Data counts
    indoor_count = len(indoor_df)
    plant_level_count = len(plant_level_df)
    outdoor_count = len(outdoor_df)
    weather_count = len(weather_df)

    # Check date ranges
    def date_range_str(df, time_col="time"):
        if df.empty:
            return "No data"
        col = time_col if time_col in df.columns else "datetime"
        dates = pd.to_datetime(df[col], utc=True)
        return f"{dates.min().date()} to {dates.max().date()}"

    indoor_range = date_range_str(indoor_df)
    plant_level_range = date_range_str(plant_level_df)
    outdoor_range = date_range_str(outdoor_df)
    weather_range = date_range_str(weather_df, "datetime")

    # Align data for scatter plot (Stage 1: weather vs outdoor)
    stage1_merged = align_weather_outdoor_hourly(
        weather_df, outdoor_df, min_lux=10.0, min_radiation=0.0
    )
    if "solar_radiation" in stage1_merged.columns:
        stage1_merged = stage1_merged[stage1_merged["solar_radiation"] > 0]

    # Create scatter plot
    if not stage1_merged.empty:
        fig = px.scatter(
            stage1_merged,
            x="solar_radiation",
            y="lux",
            title="Stage 1: OpenMeteo Solar Radiation vs s1000 Lux",
            labels={"solar_radiation": "OpenMeteo Solar Radiation (W/m²)", "lux": "s1000 Lux"},
        )
        fig.update_layout(height=500)
        scatter_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    else:
        scatter_html = "<p>No aligned data for scatter plot</p>"

    # Calculate correlation comparison using extracted function
    corr_stats = calculate_correlation_comparison(stage1_merged, "solar_radiation", "lux")
    corr = corr_stats["hourly_corr"]
    daily_corr = corr_stats["daily_corr"]
    daily_samples = corr_stats["daily_samples"]

    # Analyze reporting frequency using extracted function
    freq_stats = analyze_reporting_frequency(outdoor_df, "time")
    median_interval = freq_stats["median_interval_minutes"]
    readings_per_hour = freq_stats["readings_per_hour"]
    days_with_few = freq_stats["days_with_few_readings"]
    total_days = freq_stats["total_days"]

    # =========================================================================
    # Stage 2 Diagnostics: s1000 → s2100-01-par (Above-Lamp PAR)
    # =========================================================================
    stage2_sections = []

    if not indoor_df.empty and not plant_level_df.empty:
        # 1. Lamp Profile Summary
        lamp_profile = derive_daily_lamp_profile(indoor_df, plant_level_df)
        if not lamp_profile.empty:
            days_with_lamp = int(lamp_profile["lamp_power_par"].notna().sum())
            total_profile_days = len(lamp_profile)
            lamp_powers = lamp_profile["lamp_power_par"].dropna()
            median_lamp_power = float(lamp_powers.median()) if len(lamp_powers) > 0 else 0.0

            # Average lamp schedule hours (lamp_end - lamp_start + 1 for days with lamps)
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

            stage2_sections.append(f"""
                <div class="diag-section">
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
                </div>
            """)
        else:
            stage2_sections.append("""
                <div class="diag-section">
                    <h3>Lamp Profile Summary</h3>
                    <small>No overlapping days between sensors
                       for lamp profile derivation.</small>
                </div>
            """)

        # 2. Stage 2 Scatter: s1000 → s2100-01-par (current training target)
        if not outdoor_df.empty:
            # s1000 → s2100-01-par (above lamp, no lamp contamination)
            above_lamp_stage = align_outdoor_to_indoor_daily(outdoor_df, indoor_df)

            if not above_lamp_stage.empty:
                fig_roof = go.Figure()
                fig_roof.add_trace(go.Scatter(
                    x=above_lamp_stage["lux_sum"],
                    y=above_lamp_stage["par_sum"],
                    mode="markers",
                    name="s1000 → s2100-01-par",
                    marker={"color": "#3498db", "size": 6, "opacity": 0.6},
                ))
                fig_roof.update_layout(
                    title="Stage 2: s1000 Daily Lux → s2100-01-par (above lamp)",
                    xaxis_title="s1000 Daily Lux Sum",
                    yaxis_title="s2100-01-par Daily PAR Sum",
                    height=400,
                )
                roof_html = fig_roof.to_html(full_html=False, include_plotlyjs=False)
            else:
                roof_html = "<p>No aligned data for s1000 → s2100-01-par</p>"

            stage2_sections.append(f"""
                <div class="diag-section">
                    <h3>Scatter: s1000 → s2100-01-par (Daily)</h3>
                    {roof_html}
                </div>
            """)

            # 3. Stage 2 Correlation + model attenuation factor
            corr_parts = []

            if not above_lamp_stage.empty and len(above_lamp_stage) >= 2:
                r_roof = float(above_lamp_stage["lux_sum"].corr(above_lamp_stage["par_sum"]))
                r_roof = r_roof if pd.notna(r_roof) else 0.0
                n_roof = len(above_lamp_stage)
                corr_parts.append(f"""
                    <article>
                        <div class="stat-value">{r_roof:.3f}</div>
                        <small>Stage 2: s1000 → s2100-01 (r) - {n_roof} days</small>
                    </article>
                """)

            # s2100-01-par → s2100-02-par (attenuation correlation)
            above = indoor_df.copy()
            plant = plant_level_df.copy()
            above["time"] = pd.to_datetime(above["time"], utc=True)
            plant["time"] = pd.to_datetime(plant["time"], utc=True)
            above["date"] = above["time"].dt.date
            plant["date"] = plant["time"].dt.date
            above_daily = above.groupby("date").agg({"value": "sum"}).reset_index()
            above_daily.columns = ["date", "above_par_sum"]
            plant_daily = plant.groupby("date").agg({"value": "sum"}).reset_index()
            plant_daily.columns = ["date", "plant_par_sum"]
            internal_stage = above_daily.merge(plant_daily, on="date", how="inner")
            internal_stage = internal_stage[
                (internal_stage["above_par_sum"] > 0) & (internal_stage["plant_par_sum"] > 0)
            ]

            if not internal_stage.empty and len(internal_stage) >= 2:
                r_int = float(
                    internal_stage["above_par_sum"].corr(internal_stage["plant_par_sum"])
                )
                r_int = r_int if pd.notna(r_int) else 0.0
                n_int = len(internal_stage)
                corr_parts.append(f"""
                    <article>
                        <div class="stat-value">{r_int:.3f}</div>
                        <small>Attenuation: s2100-01 → s2100-02 (r) - {n_int} days</small>
                    </article>
                """)

            # Show stored model attenuation factor if available
            model = get_model()
            if model.stats and model.stats.attenuation_factor != 1.0:
                corr_parts.append(f"""
                    <article>
                        <div class="stat-value">{model.stats.attenuation_factor:.3f}</div>
                        <small>Model attenuation factor</small>
                    </article>
                """)

            if corr_parts:
                stage2_sections.append(f"""
                    <div class="diag-section">
                        <h3>Stage 2 Correlation</h3>
                        <div class="stats-grid">
                            {''.join(corr_parts)}
                        </div>
                    </div>
                """)

            # 4. Attenuation Validation: s2100-01-par → s2100-02-par scatter
            if not internal_stage.empty:
                fig_int = go.Figure()
                fig_int.add_trace(go.Scatter(
                    x=internal_stage["above_par_sum"],
                    y=internal_stage["plant_par_sum"],
                    mode="markers",
                    name="s2100-01-par → s2100-02-par",
                    marker={"color": "#9b59b6", "size": 6, "opacity": 0.6},
                ))
                fig_int.update_layout(
                    title="Attenuation Validation: s2100-01-par → s2100-02-par",
                    xaxis_title="s2100-01-par Daily PAR Sum (above lamp)",
                    yaxis_title="s2100-02-par Daily PAR Sum (plant level)",
                    height=400,
                )
                int_html = fig_int.to_html(full_html=False, include_plotlyjs=False)
            else:
                int_html = "<p>No aligned data for s2100-01-par → s2100-02-par</p>"

            stage2_sections.append(f"""
                <div class="diag-section">
                    <h3>Scatter: s2100-01-par → s2100-02-par (Attenuation Validation)</h3>
                    {int_html}
                </div>
            """)

            # 5. Attenuation Ratio: corrected s2100-02-par / s2100-01-par
            #    Must use lamp-corrected data, otherwise ratio is
            #    (natural+lamp)/natural which is meaningless.
            if not lamp_profile.empty and lamp_profile["lamp_power_par"].notna().any():
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
            else:
                ratio_df = pd.DataFrame()

            if not ratio_df.empty and len(ratio_df) >= 2:
                ratio_df["ratio"] = (
                    ratio_df["plant_par_sum"] / ratio_df["above_par_sum"]
                )
                ratio_df["date"] = pd.to_datetime(ratio_df["date"])
                ratio_df = ratio_df.sort_values("date")

                median_ratio = float(ratio_df["ratio"].median())
                min_ratio = float(ratio_df["ratio"].min())
                max_ratio = float(ratio_df["ratio"].max())

                # Rolling median to show seasonal trend
                window = min(14, len(ratio_df))
                ratio_df["rolling_median"] = (
                    ratio_df["ratio"].rolling(window, center=True, min_periods=3).median()
                )

                # Deviation from rolling median to find local outliers
                ratio_df["deviation"] = ratio_df["ratio"] - ratio_df["rolling_median"]
                dev_std = float(ratio_df["deviation"].std())
                outlier_mask = ratio_df["deviation"] < -2 * dev_std
                n_outliers = int(outlier_mask.sum())
                clean_n = len(ratio_df) - n_outliers

                # Time series with rolling median
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
                fig_ratio.update_layout(
                    title="Daily Attenuation Ratio (lamp-corrected s2100-02 / s2100-01)",
                    xaxis_title="",
                    yaxis_title="Ratio (corrected plant / above-lamp)",
                    height=400,
                    legend={"orientation": "h", "yanchor": "bottom", "y": 1.02,
                            "xanchor": "right", "x": 1},
                )
                ratio_chart_html = fig_ratio.to_html(
                    full_html=False, include_plotlyjs=False
                )

                # Trend assessment: range of rolling median
                rolling_clean = ratio_df["rolling_median"].dropna()
                if len(rolling_clean) >= 2:
                    trend_min = float(rolling_clean.min())
                    trend_max = float(rolling_clean.max())
                    trend_range = trend_max - trend_min
                    trend_pct = trend_range / median_ratio * 100
                    trend_label = f"{trend_min:.3f} – {trend_max:.3f} ({trend_pct:.0f}% swing)"
                else:
                    trend_label = "-"

                # Show model's stored factor for comparison
                model_factor_html = ""
                if model.stats and model.stats.attenuation_factor != 1.0:
                    model_factor_html = f"""
                        <article>
                            <div class="stat-value">{model.stats.attenuation_factor:.3f}</div>
                            <small>Model factor (stored)</small>
                        </article>
                    """

                stage2_sections.append(f"""
                    <div class="diag-section">
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
                    </div>
                """)

    else:
        stage2_sections.append("""
            <div class="diag-section">
                <h3>Stage 2 Data</h3>
                <small>Missing sensor data for Stage 2 diagnostics.
                   Need both s2100-01-par and s2100-02-par readings.</small>
            </div>
        """)

    stage2_html = "\n".join(stage2_sections)

    extra_css = """
        .diag-section { margin: 20px 0; padding: 15px; background: #f9f9f9;
                       border-radius: 8px; }
        .diag-section h3 { margin-top: 0; }
    """

    warn_class = "warning" if days_with_few > 10 else ""
    daily_class = "success" if daily_corr > corr else ""

    content = f"""
        <h1>Model Training Diagnostic</h1>
        <small>Using <strong>direct_radiation</strong> from OpenMeteo</small>

        <div class="diag-section">
            <h3>Raw Data Counts</h3>
            <div class="stats-grid cols-4">
                <article>
                    <div class="stat-value">{indoor_count:,}</div>
                    <small>Above-lamp PAR ({NATURAL_LIGHT_SENSOR})</small>
                </article>
                <article>
                    <div class="stat-value">{plant_level_count:,}</div>
                    <small>Plant-level PAR ({TOTAL_LIGHT_SENSOR})</small>
                </article>
                <article>
                    <div class="stat-value">{outdoor_count:,}</div>
                    <small>s1000 readings</small>
                </article>
                <article>
                    <div class="stat-value">{weather_count:,}</div>
                    <small>OpenMeteo hours</small>
                </article>
            </div>
            <small>
                Above-lamp: {indoor_range}<br>
                Plant-level: {plant_level_range}<br>
                Outdoor: {outdoor_range}<br>
                Weather: {weather_range}
            </small>
        </div>

        <div class="diag-section">
            <h3>s1000 Reporting</h3>
            <p>Median interval: <strong>{median_interval:.1f} min</strong>
               (~{readings_per_hour:.0f} readings/hour)</p>
        </div>

        <div class="diag-section">
            <h3>Stage 1: OpenMeteo → s1000 Correlation</h3>
            <div class="stats-grid">
                <article>
                    <div class="stat-value">{corr:.3f}</div>
                    <small>Hourly (r) - {len(stage1_merged)} samples</small>
                </article>
                <article>
                    <div class="stat-value {daily_class}">{daily_corr:.3f}</div>
                    <small>Daily totals (r) - {daily_samples} days</small>
                </article>
                <article>
                    <div class="stat-value {warn_class}">{days_with_few}/{total_days}</div>
                    <small>Days with &lt;20 readings</small>
                </article>
            </div>
        </div>

        <div class="diag-section">
            <h3>Stage 1: Scatter (OpenMeteo vs s1000)</h3>
            {scatter_html}
        </div>

        <hr>
        <h2>Stage 2 &amp; Attenuation</h2>
        {stage2_html}
    """

    return render_page(
        "Model Diagnostic - WP6 Red",
        content,
        extra_css=extra_css,
        show_back_link=True, back_url="/dli/model",
    )
