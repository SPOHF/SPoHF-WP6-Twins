"""Red dashboard DLI endpoints: overview, history, forecast, performance."""

import os
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    NATURAL_LIGHT_SENSOR,
    SECONDS_PER_HOUR,
    TOTAL_LIGHT_SENSOR,
    UMOL_TO_MOL,
    build_lamp_schedules,
    calculate_daily_dli,
    calculate_dli_trendline,
    calculate_hourly_par,
    calculate_lamp_contribution,
    compute_daily_predicted_dli,
    estimate_hourly_natural_par,
    estimate_remaining_dli,
    fetch_weather_for_range,
    get_model,
    infer_lamp_schedule_hourly,
    predict_natural_dli_from_weather,
    try_infer_lamp_from_day,
)
from wp6_data.shared import (
    make_line_chart,
    make_schedule_chart,
    render_chart_page,
    render_date_filter,
    render_page,
    resolve_date_range,
)

router = APIRouter(prefix="/dli")


@router.get("", response_class=HTMLResponse)
async def dli_home(user: str = Depends(deps.verify_auth)) -> str:
    """DLI dashboard overview page."""
    if not deps.db:
        return render_page("DLI - WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    # Get model status for the card
    model = get_model()
    user_is_admin = deps.is_admin(user)

    # Build model card based on status and permissions
    if model.is_trained() and model.stats:
        trained_date = model.stats.training_date.strftime("%Y-%m-%d")
        r2 = model.stats.r2_score
        model_status = f"""
            <p class="success">Trained: {trained_date}</p>
            <small>R² = {r2:.3f}</small>
        """
    else:
        model_status = "<small>Not trained</small>"

    if user_is_admin:
        model_card = f"""
            <article>
                <h3>Prediction Model</h3>
                <p>Train ML model to predict indoor PAR from weather data.</p>
                {model_status}
                <a href="/dli/model" class="btn">Manage Model</a>
            </article>
        """
    else:
        model_card = f"""
            <article class="card-disabled">
                <h3>Prediction Model</h3>
                <p>ML model to predict indoor PAR from weather data.</p>
                {model_status}
                <span class="btn-disabled">Admin only</span>
            </article>
        """

    extra_css = """
        .grid { display: grid; gap: 20px;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
        .grid article { margin-bottom: 0; }
        .grid article h3 { margin-top: 0; }
        .card-primary { border: 2px solid var(--pico-primary-background); }
        .card-disabled { opacity: 0.6; }
        .btn { display: inline-block; padding: 8px 16px; background: var(--pico-primary-background);
               color: var(--pico-primary-inverse); text-decoration: none; border-radius: 4px;
               margin-right: 8px; }
        .btn:hover { opacity: 0.85; text-decoration: none; }
        .btn-disabled { display: inline-block; padding: 8px 16px; background: #ccc;
                       color: #666; border-radius: 4px; font-size: 0.9em; }
    """

    content = f"""
        <h1>DLI Dashboard</h1>
        <p>Daily Light Integral analysis for PAR sensors.</p>

        <div class="grid">
            <article>
                <h3>PAR Chart</h3>
                <p>Raw PAR readings: light above lamps vs under lamps.</p>
                <a href="/dli/chart" class="btn">View Chart</a>
            </article>

            <article>
                <h3>History</h3>
                <p>Compare natural light vs total light (with lamps) over time.</p>
                <a href="/dli/history" class="btn">View History</a>
            </article>

            <article class="card-primary">
                <h3>Forecast</h3>
                <p>Predict plant light based on schedule and weather data.</p>
                <a href="/dli/forecast" class="btn">View Forecast</a>
            </article>

            <article>
                <h3>Performance</h3>
                <p>Compare model predictions with actual sensor readings over time.</p>
                <a href="/dli/performance" class="btn">View Performance</a>
            </article>

            {model_card}
        </div>
    """

    return render_page("DLI Dashboard - WP6 Red", content, extra_css=extra_css, show_back_link=True)


@router.get("/chart", response_class=HTMLResponse)
async def dli_chart(
    user: str = Depends(deps.verify_auth),
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Simple PAR chart showing light above lamps vs under lamps."""
    if not deps.db:
        return render_page("DLI Chart - WP6 Red", "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
    except Exception as e:
        return render_page("DLI Chart - WP6 Red", f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Rename device IDs to friendly labels for the chart legend
    device_labels = {
        NATURAL_LIGHT_SENSOR: "Above Lamps (natural)",
        TOTAL_LIGHT_SENSOR: "Under Lamps (total)",
    }
    if not df.empty:
        df = df.copy()
        df["device"] = df["device"].map(device_labels).fillna(df["device"])

    fig = make_line_chart(df, title="PAR - Above Lamps vs Under Lamps")

    return render_chart_page(df, fig, "DLI Chart - WP6 Red", start, end, back_url="/dli")


@router.get("/history", response_class=HTMLResponse)
async def dli_history(
    user: str = Depends(deps.verify_auth),
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """DLI chart comparing natural light vs total light over time."""
    if not deps.db:
        return render_page("DLI History - WP6 Red", "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        par_df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
    except Exception as e:
        return render_page("DLI History - WP6 Red", f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    filter_html = render_date_filter(start, end)

    if par_df.empty:
        return render_page(
            "DLI History - WP6 Red",
            filter_html + "<h1>No PAR data found</h1>",
            show_back_link=True, back_url="/dli",
        )

    # Calculate DLI per device per day
    dli_df = calculate_daily_dli(par_df)

    if dli_df.empty:
        return render_page(
            "DLI History - WP6 Red",
            filter_html + "<h1>Insufficient data for DLI calculation</h1>",
            show_back_link=True, back_url="/dli",
        )

    # Rename devices to friendly labels
    device_labels = {
        NATURAL_LIGHT_SENSOR: "Natural Light",
        TOTAL_LIGHT_SENSOR: "Total Light",
    }
    dli_df["source"] = dli_df["device"].map(device_labels).fillna(dli_df["device"])

    # Pivot data for cleaner charts
    natural_data = dli_df[dli_df["device"] == NATURAL_LIGHT_SENSOR][
        ["date", "dli", "photoperiod_hours"]
    ].rename(columns={"dli": "natural_dli", "photoperiod_hours": "natural_hours"})
    total_data = dli_df[dli_df["device"] == TOTAL_LIGHT_SENSOR][
        ["date", "dli", "photoperiod_hours"]
    ].rename(columns={"dli": "total_dli", "photoperiod_hours": "total_hours"})

    chart_df = natural_data.merge(total_data, on="date", how="outer").sort_values("date")

    # Create DLI line chart with area fill
    fig_dli = go.Figure()
    fig_dli.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["total_dli"],
        name="Total Light", mode="lines+markers",
        line={"color": "#2ecc71", "width": 2},
        marker={"size": 6},
        fill="tozeroy", fillcolor="rgba(46, 204, 113, 0.2)",
    ))
    fig_dli.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["natural_dli"],
        name="Natural Light", mode="lines+markers",
        line={"color": "#3498db", "width": 2},
        marker={"size": 6},
        fill="tozeroy", fillcolor="rgba(52, 152, 219, 0.2)",
    ))

    # Add trendline for Total DLI
    total_valid = chart_df.dropna(subset=["total_dli"])
    if len(total_valid) >= 2:
        trendline_y, slope_per_day = calculate_dli_trendline(
            total_valid["date"].tolist(),
            total_valid["total_dli"].values,
        )
        trend_label = f"Trend ({slope_per_day:+.2f}/day)"
        fig_dli.add_trace(go.Scatter(
            x=total_valid["date"], y=trendline_y,
            name=trend_label, mode="lines",
            line={"color": "#e74c3c", "width": 2, "dash": "dash"},
        ))

    fig_dli.update_layout(
        title="Daily Light Integral (DLI)",
        yaxis_title="DLI (mol/m²/day)",
        xaxis_title="",
        height=400,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"t": 60, "b": 40},
    )
    chart_dli_html = fig_dli.to_html(full_html=False, include_plotlyjs="cdn")

    # Create photoperiod chart
    fig_hours = go.Figure()
    fig_hours.add_trace(go.Bar(
        x=chart_df["date"], y=chart_df["total_hours"],
        name="Total Hours", marker_color="#2ecc71",
    ))
    fig_hours.update_layout(
        title="Photoperiod (hours of light)",
        yaxis_title="Hours",
        xaxis_title="",
        height=300,
        hovermode="x unified",
        margin={"t": 60, "b": 40},
    )
    chart_hours_html = fig_hours.to_html(full_html=False, include_plotlyjs=False)

    # Summary stats
    days_count = len(chart_df)
    natural_avg = chart_df["natural_dli"].mean() if "natural_dli" in chart_df else 0
    total_avg = chart_df["total_dli"].mean() if "total_dli" in chart_df else 0
    hours_avg = chart_df["total_hours"].mean() if "total_hours" in chart_df else 0

    extra_css = """
        .chart-section { margin-bottom: 30px; }
        td, th { text-align: center; }
    """

    stats_html = f"""
        <div class="stats-grid cols-4">
            <article>
                <div class="stat-value">{total_avg:.1f}</div>
                <small>Avg Total DLI</small>
            </article>
            <article>
                <div class="stat-value">{natural_avg:.1f}</div>
                <small>Avg Natural DLI</small>
            </article>
            <article>
                <div class="stat-value">{hours_avg:.1f}h</div>
                <small>Avg Photoperiod</small>
            </article>
            <article>
                <div class="stat-value">{days_count}</div>
                <small>Days</small>
            </article>
        </div>
    """

    # Build data table
    table_df = chart_df.sort_values("date", ascending=False)
    table_rows = []
    for _, row in table_df.iterrows():
        natural_dli_val = f"{row['natural_dli']:.1f}" if pd.notna(row.get("natural_dli")) else "-"
        total_dli_val = f"{row['total_dli']:.1f}" if pd.notna(row.get("total_dli")) else "-"
        total_hrs = f"{row['total_hours']:.1f}" if pd.notna(row.get("total_hours")) else "-"

        # Calculate lamp contribution
        lamp_dli = calculate_lamp_contribution(
            row.get("total_dli") if pd.notna(row.get("total_dli")) else None,
            row.get("natural_dli") if pd.notna(row.get("natural_dli")) else None,
        )
        lamp_str = f"{lamp_dli:.1f}" if lamp_dli is not None else "-"

        table_rows.append(f"""
            <tr>
                <td>{row['date']}</td>
                <td>{natural_dli_val}</td>
                <td>{total_dli_val}</td>
                <td>{lamp_str}</td>
                <td>{total_hrs}</td>
            </tr>
        """)

    table_html = f"""
        <details>
            <summary>View Data Table</summary>
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Natural DLI</th>
                        <th>Total DLI</th>
                        <th>Lamp DLI</th>
                        <th>Photoperiod</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>
        </details>
    """

    content = f"""
        {filter_html}
        {stats_html}
        <div class="chart-section">{chart_dli_html}</div>
        <div class="chart-section">{chart_hours_html}</div>
        {table_html}
    """

    return render_page(
        "DLI History - WP6 Red",
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )


@router.get("/forecast", response_class=HTMLResponse)
async def dli_forecast(
    user: str = Depends(deps.verify_auth),
    start_date: Annotated[date | None, Query(description="Start date")] = None,
    end_date: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Analyze light schedule with predictions based on inferred lamp schedule."""
    if not deps.db:
        return render_page("DLI Forecast - WP6 Red", "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    # Default to today
    today = date.today()
    if start_date is None:
        start_date = today
    if end_date is None:
        end_date = start_date

    # Ensure valid range
    if end_date < start_date:
        end_date = start_date

    sensor = os.getenv("WP6_RED_DLI_SCHEDULE_SENSOR", "s2100-02-par")
    yesterday = today - timedelta(days=1)

    # Reference day for lamp inference: the day before the viewed range,
    # but never later than yesterday (we need a full day of actual data).
    lamp_ref_day = min(start_date - timedelta(days=1), yesterday)

    # Get reference day's data for inferring lamp schedule
    lamp_ref_start = datetime(lamp_ref_day.year, lamp_ref_day.month, lamp_ref_day.day, tzinfo=UTC)
    lamp_ref_end = lamp_ref_start + timedelta(days=1) - timedelta(seconds=1)

    try:
        lamp_ref_par_df = await deps.db.get_par_readings(
            device_ids=[sensor], start=lamp_ref_start, end=lamp_ref_end
        )
    except Exception as e:
        return render_page("DLI Forecast - WP6 Red", f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Calculate lamp reference day's DLI (also used for yesterday card when applicable)
    lamp_ref_dli = 0.0
    if not lamp_ref_par_df.empty:
        lamp_ref_daily = calculate_daily_dli(lamp_ref_par_df)
        if not lamp_ref_daily.empty:
            lamp_ref_dli = lamp_ref_daily["dli"].iloc[0]

    # Get weather client and model
    client = deps.get_weather_client()
    model = get_model()

    # Infer lamp schedule from reference day (hourly: actual - predicted natural)
    inferred_lamp_hourly: dict[int, float] = {}  # hour -> lamp PAR
    lamp_ref_natural_dli = 0.0
    lamp_ref_forecast = None
    if not lamp_ref_par_df.empty and model.is_trained():
        try:
            lamp_ref_weather = await client.get_historical(lamp_ref_day, lamp_ref_day)
            if lamp_ref_weather:
                forecast = lamp_ref_weather[0]
                lamp_ref_forecast = forecast
                lamp_ref_natural_dli = model.predict_dli(forecast.total_radiation)

                # Calculate hourly averages from actual data
                lamp_ref_hourly = calculate_hourly_par(lamp_ref_par_df)

                # Infer lamp schedule using extracted function
                inferred_lamp_hourly = infer_lamp_schedule_hourly(
                    lamp_ref_hourly,
                    lamp_ref_natural_dli,
                    forecast.hourly,
                    forecast.total_radiation,
                )
        except Exception:
            pass  # Fall back to no lamp inference

    # Get data for selected date range
    range_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
    range_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=UTC)
    range_end = range_end + timedelta(days=1) - timedelta(seconds=1)

    try:
        par_df = await deps.db.get_par_readings(
            device_ids=[sensor], start=range_start, end=range_end
        )
    except Exception as e:
        return render_page("DLI Forecast - WP6 Red", f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Prepare actual data for chart (raw readings)
    actual_df = None
    if not par_df.empty:
        actual_df = par_df.rename(columns={"time": "datetime", "value": "par"})

    # Get weather for date range (for predictions)
    predicted_df = None
    natural_df = None
    lamp_schedules: dict[date, dict[int, float]] = {}
    last_good_schedule = inferred_lamp_hourly  # seed from lamp_ref_day

    if model.is_trained():
        try:
            forecasts = await fetch_weather_for_range(client, start_date, end_date)
            daily_natural_dli = predict_natural_dli_from_weather(model, forecasts)

            # Build per-day lamp schedules from previous day's actual data
            forecast_by_date = {f.date: f for f in forecasts}
            if lamp_ref_forecast is not None:
                forecast_by_date[lamp_ref_day] = lamp_ref_forecast

            lamp_schedules, last_good_schedule = build_lamp_schedules(
                par_df, forecasts, forecast_by_date, model,
                inferred_lamp_hourly, lamp_ref_day,
            )

            predicted_records = []
            natural_records = []

            for forecast in forecasts:
                day_natural_dli = daily_natural_dli[forecast.date]

                for h in forecast.hourly:
                    # Calculate natural PAR for this hour using extracted function
                    natural_par = estimate_hourly_natural_par(
                        day_natural_dli, h.solar_radiation, forecast.total_radiation
                    )

                    natural_records.append({"datetime": h.datetime, "par": natural_par})

                    # Calculate predicted PAR = inferred lamp + natural
                    day_lamp = lamp_schedules.get(forecast.date, last_good_schedule)
                    lamp_par = day_lamp.get(h.datetime.hour, 0.0)
                    predicted_par = natural_par + lamp_par
                    predicted_records.append({"datetime": h.datetime, "par": predicted_par})

            if predicted_records:
                predicted_df = pd.DataFrame(predicted_records)
                predicted_df["datetime"] = pd.to_datetime(predicted_df["datetime"], utc=True)

            if natural_records:
                natural_df = pd.DataFrame(natural_records)
                natural_df["datetime"] = pd.to_datetime(natural_df["datetime"], utc=True)

        except Exception:
            pass  # Predictions unavailable

    # Calculate daily DLI values for annotations and cards
    daily_dli: dict[date, dict] = {}  # date -> {actual, predicted, natural}
    tomorrow = today + timedelta(days=1)

    # Yesterday's DLI for the card: reuse lamp_ref data when it IS yesterday,
    # otherwise fetch separately.
    if lamp_ref_day == yesterday:
        yesterday_dli = lamp_ref_dli
        yesterday_natural_dli = lamp_ref_natural_dli
    else:
        yesterday_dli = 0.0
        yesterday_natural_dli = 0.0
        try:
            y_start = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=UTC)
            y_end = y_start + timedelta(days=1) - timedelta(seconds=1)
            y_par_df = await deps.db.get_par_readings(
                device_ids=[sensor], start=y_start, end=y_end
            )
            if not y_par_df.empty:
                y_daily = calculate_daily_dli(y_par_df)
                if not y_daily.empty:
                    yesterday_dli = y_daily["dli"].iloc[0]
                y_weather = await client.get_historical(yesterday, yesterday)
                if y_weather:
                    yesterday_natural_dli = model.predict_dli(y_weather[0].total_radiation)
        except Exception:
            pass

    if yesterday_dli > 0:
        daily_dli[yesterday] = {"actual": yesterday_dli}
    if yesterday_natural_dli > 0:
        daily_dli.setdefault(yesterday, {})["natural"] = yesterday_natural_dli

    # Actual DLI per day from selected range
    if not par_df.empty:
        actual_daily = calculate_daily_dli(par_df)
        for _, row in actual_daily.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            daily_dli.setdefault(d, {})["actual"] = row["dli"]

    # Predicted/natural DLI per day (from forecasts)
    if predicted_df is not None and not predicted_df.empty:
        predicted_df["date"] = predicted_df["datetime"].dt.date
        for d, grp in predicted_df.groupby("date"):
            dli = grp["par"].sum() * SECONDS_PER_HOUR / UMOL_TO_MOL
            daily_dli.setdefault(d, {})["predicted"] = dli

    if natural_df is not None and not natural_df.empty:
        natural_df["date"] = natural_df["datetime"].dt.date
        for d, grp in natural_df.groupby("date"):
            dli = grp["par"].sum() * SECONDS_PER_HOUR / UMOL_TO_MOL
            daily_dli.setdefault(d, {})["natural"] = dli

    # Ensure today and tomorrow have predictions for cards (if not already in range)
    if model.is_trained():
        missing_card_dates = [
            d for d in [today, tomorrow]
            if d not in daily_dli or "predicted" not in daily_dli.get(d, {})
        ]
        if missing_card_dates:
            try:
                card_forecasts = await client.get_forecast(days=7)
                card_fc = [f for f in card_forecasts if f.date in missing_card_dates]
                if card_fc:
                    nat_map = predict_natural_dli_from_weather(model, card_fc)
                    pred_map = compute_daily_predicted_dli(
                        card_fc, nat_map, lamp_schedules, last_good_schedule
                    )
                    for f in card_fc:
                        daily_dli.setdefault(f.date, {})["predicted"] = pred_map[f.date]
                        daily_dli.setdefault(f.date, {})["natural"] = nat_map[f.date]
            except Exception:
                pass

    # For today: combine actual (observed so far) + predicted remainder
    current_hour = datetime.now(UTC).hour
    today_vals_tmp = daily_dli.get(today, {})
    has_today_data = "actual" in today_vals_tmp and "predicted" in today_vals_tmp
    if has_today_data and predicted_df is not None and not predicted_df.empty:
        remainder_dli = estimate_remaining_dli(predicted_df, today, current_hour)
        daily_dli[today]["estimated"] = today_vals_tmp["actual"] + remainder_dli

    # Build chart
    title = f"Light Schedule - {start_date}" if start_date == end_date else \
            f"Light Schedule - {start_date} to {end_date}"
    fig = make_schedule_chart(
        actual_df=actual_df,
        predicted_df=predicted_df,
        natural_df=natural_df,
        title=title,
    )

    # Add daily DLI annotations at noon of each day (at bottom to avoid legend)
    for d, values in sorted(daily_dli.items()):
        if d < start_date or d > end_date:
            continue
        noon = datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
        parts = []
        if "actual" in values:
            parts.append(f"A:{values['actual']:.1f}")
        if "predicted" in values:
            parts.append(f"P:{values['predicted']:.1f}")
        if "natural" in values:
            parts.append(f"N:{values['natural']:.1f}")
        if parts:
            fig.add_annotation(
                x=noon, y=0.02, yref="paper", yanchor="bottom",
                text="<br>".join(parts),
                showarrow=False, font={"size": 10}, bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#ccc", borderwidth=1, borderpad=4,
            )

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    # Get DLI values for yesterday, today, tomorrow cards
    yesterday_vals = daily_dli.get(yesterday, {})
    today_vals = daily_dli.get(today, {})
    tomorrow_vals = daily_dli.get(tomorrow, {})

    unit = '<span class="unit">mol/m²</span>'

    def format_card_value(vals: dict, use_estimated: bool = False) -> str:
        if use_estimated and "estimated" in vals:
            return f"{vals['estimated']:.1f}~ {unit}"
        if "actual" in vals:
            return f"{vals['actual']:.1f} {unit}"
        if "predicted" in vals:
            return f"{vals['predicted']:.1f}* {unit}"
        return "-"

    def format_card_sublabel(vals: dict) -> str:
        if "natural" in vals:
            return f"(natural: {vals['natural']:.1f})"
        return ""

    extra_css = """
        .schedule-controls { padding: 0.75rem 1rem; }
        .schedule-controls form { display: flex; gap: 1rem; align-items: end;
                                  flex-wrap: wrap; margin-bottom: 0; }
        .schedule-controls label { margin-bottom: 0; }
        .stat-value .unit { font-size: 0.5em; font-weight: normal; color: #999; }
    """

    controls_html = f"""
        <article class="schedule-controls">
            <form method="get">
                <label>Start
                    <input type="date" name="start_date" value="{start_date}"
                           onchange="this.form.submit()">
                </label>
                <label>End
                    <input type="date" name="end_date" value="{end_date}"
                           onchange="this.form.submit()">
                </label>
            </form>
        </article>
    """

    stats_html = f"""
        <div class="stats-grid">
            <article>
                <div class="stat-value">{format_card_value(yesterday_vals)}</div>
                <small>Yesterday</small><br>
                <small>{format_card_sublabel(yesterday_vals)}</small>
            </article>
            <article>
                <div class="stat-value">{format_card_value(today_vals, use_estimated=True)}</div>
                <small>Today</small><br>
                <small>{format_card_sublabel(today_vals)}</small>
            </article>
            <article>
                <div class="stat-value">{format_card_value(tomorrow_vals)}</div>
                <small>Tomorrow</small><br>
                <small>{format_card_sublabel(tomorrow_vals)}</small>
            </article>
        </div>
        <small>* predicted ~ estimated</small>
    """

    content = f"""
        <h1>DLI Forecast</h1>
        {controls_html}
        {stats_html}
        {chart_html}
        <small>
            A/P/N = Actual / Predicted / Natural DLI values per day.<br/>
            Natural light predictions are based on the current ML model.<br/>
            Total predicted is yesterday's inferred lamp schedule + natural light.
        </small>
    """

    return render_page(
        "DLI Forecast - WP6 Red",
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )


@router.get("/performance", response_class=HTMLResponse)
async def dli_performance(
    user: str = Depends(deps.verify_auth),
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Compare predicted DLI (model hindcast) with actual sensor readings."""
    if not deps.db:
        return render_page("DLI Performance - WP6 Red", "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    model = get_model()
    if not model.is_trained():
        return render_page(
            "DLI Performance - WP6 Red",
            "<h1>Model not trained</h1><p>Train the prediction model first.</p>",
            show_back_link=True, back_url="/dli",
        )

    # Default to last 30 days, always exclude today (incomplete)
    today = date.today()
    yesterday = today - timedelta(days=1)
    if start is None:
        start = today - timedelta(days=30)
    if end is None:
        end = yesterday
    end = min(end, yesterday)

    lamp_ref_day = start - timedelta(days=1)
    lamp_ref_dt = datetime(lamp_ref_day.year, lamp_ref_day.month, lamp_ref_day.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    filter_html = render_date_filter(start, end)

    # Fetch actual PAR data for both sensors (include lamp_ref_day for seed)
    try:
        par_df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=lamp_ref_dt, end=end_dt
        )
    except Exception as e:
        return render_page("DLI Performance - WP6 Red", f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Fetch weather data including lamp_ref_day for lamp inference
    client = deps.get_weather_client()
    try:
        forecasts = await fetch_weather_for_range(client, lamp_ref_day, end)
        predicted_natural = predict_natural_dli_from_weather(model, forecasts)
    except Exception as e:
        return render_page("DLI Performance - WP6 Red",
                          filter_html + f"<h1>Weather data error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Calculate actual DLI per device per day (filter to requested range only)
    actual_total_dli: dict[date, float] = {}
    actual_natural_dli: dict[date, float] = {}
    if not par_df.empty:
        daily_df = calculate_daily_dli(par_df)
        for _, row in daily_df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            if d < start or d > end:
                continue
            if row["device"] == TOTAL_LIGHT_SENSOR:
                actual_total_dli[d] = row["dli"]
            elif row["device"] == NATURAL_LIGHT_SENSOR:
                actual_natural_dli[d] = row["dli"]

    # Build lamp schedules from total sensor data (true forecast approach)
    total_par_df = par_df[par_df["device"] == TOTAL_LIGHT_SENSOR] if not par_df.empty else par_df
    forecast_by_date = {f.date: f for f in forecasts}
    seed = try_infer_lamp_from_day(total_par_df, lamp_ref_day, forecast_by_date, model)
    seed_schedule = seed if seed is not None else {}

    range_forecasts = [f for f in forecasts if start <= f.date <= end]
    lamp_schedules, last_good = build_lamp_schedules(
        total_par_df, range_forecasts, forecast_by_date, model, seed_schedule, lamp_ref_day
    )

    predicted_natural_range = {d: v for d, v in predicted_natural.items() if start <= d <= end}
    predicted_total_dli = compute_daily_predicted_dli(
        range_forecasts, predicted_natural_range, lamp_schedules, last_good
    )

    # Two modes: total (actual total vs predicted total) and natural (actual natural vs predicted)
    modes = {
        "total": {
            "actual": actual_total_dli,
            "predicted": predicted_total_dli,
            "label": "Total DLI",
            "actual_name": "Actual Total",
            "predicted_name": "Predicted Total",
        },
        "natural": {
            "actual": actual_natural_dli,
            "predicted": predicted_natural_range,
            "label": "Natural DLI",
            "actual_name": "Actual Natural",
            "predicted_name": "Predicted Natural",
        },
    }

    mode_html = {}
    for mode_key, m in modes.items():
        shared = sorted(set(m["actual"]) & set(m["predicted"]))
        if not shared:
            mode_html[mode_key] = "<p>No overlapping data for this view.</p>"
            continue

        act = [m["actual"][d] for d in shared]
        pred = [m["predicted"][d] for d in shared]
        errs = [p - a for a, p in zip(act, pred, strict=True)]
        pct_errs = [
            ((p - a) / a * 100) if a > 0 else 0.0
            for a, p in zip(act, pred, strict=True)
        ]
        abs_pct = [abs(e) for e in pct_errs]

        mape = float(np.mean(abs_pct))
        mae = float(np.mean([abs(e) for e in errs]))
        bias = float(np.mean(errs))

        # Line chart
        fig_cmp = go.Figure()
        fig_cmp.add_trace(go.Scatter(
            x=shared, y=act,
            name=m["actual_name"], mode="lines+markers",
            line={"color": "#3498db", "width": 2}, marker={"size": 6},
            hovertemplate="%{y:.1f}<extra></extra>",
        ))
        fig_cmp.add_trace(go.Scatter(
            x=shared, y=pred,
            name=m["predicted_name"], mode="lines+markers",
            line={"color": "#e74c3c", "width": 2, "dash": "dash"}, marker={"size": 6},
            hovertemplate="%{y:.1f}<extra></extra>",
        ))
        fig_cmp.add_trace(go.Scatter(
            x=list(shared) + list(reversed(shared)),
            y=pred + list(reversed(act)),
            fill="toself", fillcolor="rgba(231, 76, 60, 0.1)",
            line={"width": 0}, showlegend=False, hoverinfo="skip",
        ))
        fig_cmp.update_layout(
            title=f"Actual vs Predicted {m['label']}",
            yaxis_title="DLI (mol/m²/day)", height=400, hovermode="x unified",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02,
                    "xanchor": "right", "x": 1},
            margin={"t": 60, "b": 40},
        )
        # First mode gets plotly CDN, second reuses it
        include_js = "cdn" if mode_key == "total" else False
        chart_cmp = fig_cmp.to_html(full_html=False, include_plotlyjs=include_js)

        # Error bar chart
        bar_colors = []
        for pct in pct_errs:
            ap = abs(pct)
            if ap < 15:
                bar_colors.append("#22c55e")
            elif ap < 30:
                bar_colors.append("#f59e0b")
            else:
                bar_colors.append("#ef4444")

        fig_err = go.Figure()
        fig_err.add_trace(go.Bar(
            x=shared, y=errs, marker_color=bar_colors,
            hovertemplate="%{x}<br>Error: %{y:.1f} mol/m²/day<extra></extra>",
        ))
        fig_err.update_layout(
            title="Daily Prediction Error", yaxis_title="Error (mol/m²/day)",
            height=300, hovermode="x unified", margin={"t": 60, "b": 40},
        )
        fig_err.add_hline(y=0, line_color="black", line_width=1)
        chart_err = fig_err.to_html(full_html=False, include_plotlyjs=False)

        # Stats
        bias_lbl = "overprediction" if bias > 0 else "underprediction"
        stats = f"""
            <div class="stats-grid">
                <article>
                    <div class="stat-value">{mape:.1f}%</div>
                    <small>Avg. Error</small><br>
                    <small>Mean absolute % error</small>
                </article>
                <article>
                    <div class="stat-value">{mae:.2f}</div>
                    <small>Avg. Absolute Error</small><br>
                    <small>mol/m²/day off per day</small>
                </article>
                <article>
                    <div class="stat-value">{bias:+.2f}</div>
                    <small>Bias ({bias_lbl})</small><br>
                    <small>Systematic over/under trend</small>
                </article>
            </div>
        """

        # Table
        rows = []
        for i, d in enumerate(reversed(shared)):
            idx = len(shared) - 1 - i
            a, p, err, pct = act[idx], pred[idx], errs[idx], pct_errs[idx]
            ap = abs(pct)
            cls = "success" if ap < 15 else ("warning" if ap < 30 else "error-high")
            rows.append(f"""<tr>
                <td>{d}</td><td>{a:.2f}</td><td>{p:.2f}</td>
                <td>{err:+.2f}</td><td class="{cls}">{pct:+.1f}%</td>
            </tr>""")

        table = f"""
            <details>
                <summary>View Data Table ({len(shared)} days)</summary>
                <table><thead><tr>
                    <th>Date</th><th>{m['actual_name']}</th><th>{m['predicted_name']}</th>
                    <th>Error</th><th>Error %</th>
                </tr></thead><tbody>{''.join(rows)}</tbody></table>
            </details>
        """

        mode_html[mode_key] = f"""
            {stats}
            <div class="chart-section">{chart_cmp}</div>
            <div class="chart-section">{chart_err}</div>
            {table}
        """

    extra_css = """
        .chart-section { margin-bottom: 30px; }
        td, th { text-align: center; }
        .error-high { color: #ef4444 !important; font-weight: bold; }
        .mode-toggle { display: inline-flex; border-radius: 8px; overflow: hidden;
                       border: 2px solid var(--dashboard-primary); margin-bottom: 1rem; }
        .mode-toggle button { padding: 0.4rem 1.2rem; border: none; cursor: pointer;
                              background: transparent; color: var(--dashboard-primary);
                              font-weight: 600; transition: all 0.15s; }
        .mode-toggle button.active { background: var(--dashboard-primary); color: #fff; }
        .mode-toggle button:hover:not(.active) { background: var(--dashboard-surface); }
        .mode-view { display: none; }
        .mode-view.active { display: block; }
    """

    toggle_js = """
    <script>
    function switchMode(mode) {
        document.querySelectorAll('.mode-view').forEach(function(el) {
            el.classList.toggle('active', el.dataset.mode === mode);
        });
        document.querySelectorAll('.mode-toggle button').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        // Plotly charts rendered in hidden divs need a resize to fill correctly
        var active = document.querySelector('.mode-view.active');
        if (active) {
            active.querySelectorAll('.js-plotly-plot').forEach(function(plot) {
                Plotly.Plots.resize(plot);
            });
        }
    }
    </script>
    """

    content = f"""
        <h1>DLI Performance</h1>
        <p>Comparing model predictions with actual sensor readings.</p>
        {filter_html}
        <div class="mode-toggle">
            <button data-mode="total" class="active" onclick="switchMode('total')">
                Total DLI</button>
            <button data-mode="natural" onclick="switchMode('natural')">
                Natural Light Only</button>
        </div>
        <div class="mode-view active" data-mode="total">
            {mode_html.get("total", "<p>No data.</p>")}
        </div>
        <div class="mode-view" data-mode="natural">
            {mode_html.get("natural", "<p>No data.</p>")}
        </div>
        {toggle_js}
    """

    return render_page(
        "DLI Performance - WP6 Red",
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )
