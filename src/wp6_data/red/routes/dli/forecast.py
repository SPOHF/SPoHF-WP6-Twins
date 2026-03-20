"""GET /dli/forecast — Analyze light schedule with predictions based on inferred lamp schedule."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    DEFAULT_FORECAST_CENTER_DAYS,
    SECONDS_PER_HOUR,
    TOTAL_LIGHT_SENSOR,
    UMOL_TO_MOL,
    build_lamp_schedules,
    calculate_daily_dli,
    calculate_hourly_par,
    compute_daily_predicted_dli,
    estimate_hourly_natural_par,
    estimate_remaining_dli,
    fetch_weather_for_range,
    get_model,
    infer_lamp_schedule_hourly,
    predict_natural_dli_from_weather,
)
from wp6_data.shared import make_schedule_chart, render_page, utc_day_bounds

router = APIRouter()


@router.get("/forecast", response_class=HTMLResponse)
async def dli_forecast(
    start_date: Annotated[date | None, Query(description="Start date")] = None,
    end_date: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Analyze light schedule with predictions based on inferred lamp schedule."""
    if not deps.db:
        return render_page("DLI Forecast - WP6 Red", "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    # Default to a 5-day window centred on today (today-2 … today+2)
    today = date.today()
    if start_date is None:
        start_date = today - timedelta(days=DEFAULT_FORECAST_CENTER_DAYS)
    if end_date is None:
        end_date = today + timedelta(days=DEFAULT_FORECAST_CENTER_DAYS)

    # Ensure valid range
    if end_date < start_date:
        end_date = start_date

    sensor = TOTAL_LIGHT_SENSOR
    yesterday = today - timedelta(days=1)

    # Reference day for lamp inference: the day before the viewed range,
    # but never later than yesterday (we need a full day of actual data).
    lamp_ref_day = min(start_date - timedelta(days=1), yesterday)

    # Get reference day's data for inferring lamp schedule
    lamp_ref_start, lamp_ref_end = utc_day_bounds(lamp_ref_day)

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
    range_start, _ = utc_day_bounds(start_date)
    _, range_end = utc_day_bounds(end_date)

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
            y_start, y_end = utc_day_bounds(yesterday)
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
