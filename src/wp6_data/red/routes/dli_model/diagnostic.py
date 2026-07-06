"""GET /dli/model/diagnostic — Diagnostic view to investigate model training data."""

from datetime import UTC, datetime

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.red.dli import (
    DEFAULT_TRAINING_START,
    NATURAL_LIGHT_SENSOR,
    TOTAL_LIGHT_SENSOR,
    WEATHER_STATION_SENSOR,
    derive_daily_lamp_profile,
    get_model,
    subtract_lamp_from_sensor,
)
from wp6_data.red.dli import data as dli_data
from wp6_data.shared import render_page, render_stat_grid, render_stat_tile

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI Model Diagnostic"

@router.get("/diagnostic", response_class=HTMLResponse)
async def dli_model_diagnostic() -> str:
    """Diagnostic view to investigate model training data."""
    if not dli_data.is_connected():
        return render_page(
            PAGE_TITLE,
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
        indoor_df = await dli_data.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        plant_level_df = await dli_data.get_par_readings(
            device_ids=[TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
        outdoor_df = await dli_data.get_weather_station_readings(start=start_dt, end=end_dt)
    except Exception as e:
        return render_page(
            PAGE_TITLE,
            f"<h1>Error fetching data</h1><p>{e}</p>",
            show_back_link=True, back_url="/dli/model",
        )

    # --- Section 1: Raw Data Counts ---
    def date_range_str(df, time_col="time"):
        if df.empty:
            return "No data"
        dates = pd.to_datetime(df[time_col], utc=True)
        return f"{dates.min().date()} to {dates.max().date()}"

    counts_grid = render_stat_grid([
        (f"{len(indoor_df):,}", f"Above-lamp PAR ({NATURAL_LIGHT_SENSOR})"),
        (f"{len(plant_level_df):,}", f"Plant-level PAR ({TOTAL_LIGHT_SENSOR})"),
        (f"{len(outdoor_df):,}", f"{WEATHER_STATION_SENSOR} readings"),
    ])
    counts_html = f"""
        <article>
            <h3>Raw Data Counts</h3>
            {counts_grid}
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

            lamp_grid = render_stat_grid([
                (f"{days_with_lamp}/{total_profile_days}", "Days with lamp detected"),
                (f"{median_lamp_power:.0f}", "Median lamp PAR (μmol/m²/s)"),
                (f"{avg_lamp_hours:.1f}h", "Avg lamp schedule"),
            ])
            lamp_html = f"""
                <article>
                    <h3>Lamp Profile Summary</h3>
                    <p>Derived from {NATURAL_LIGHT_SENSOR} (above lamp) and
                       {TOTAL_LIGHT_SENSOR} (plant level)</p>
                    {lamp_grid}
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
                    model_factor_html = render_stat_tile(
                        f"{model.stats.attenuation_factor:.3f}",
                        "Model factor (stored)",
                    )

                ratio_grid = render_stat_grid([
                    (f"{median_ratio:.3f}", "Live median"),
                    model_factor_html,
                    (f"{min_ratio:.3f} – {max_ratio:.3f}", "Range (all days)"),
                    (trend_label, "Rolling median range"),
                    render_stat_tile(
                        f"{n_outliers}",
                        f"Occlusion days ({clean_n} clean)",
                        value_class="warning",
                    ),
                ], cols="auto")

                ratio_html = f"""
                    <article>
                        <h3>Attenuation: s2100-01 → Plant-Level</h3>
                        <small>Ratio of lamp-corrected plant-level to
                           above-lamp daily PAR (natural light only).
                           Rolling median shows seasonal trend.
                           Red crosses = days &gt;2&sigma; below local trend
                           (likely plant occlusion).</small>
                        {ratio_grid}
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
        PAGE_TITLE,
        content,
        show_back_link=True, back_url="/dli/model",
    )
