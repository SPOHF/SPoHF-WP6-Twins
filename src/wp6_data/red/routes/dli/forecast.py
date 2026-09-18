"""GET /dli/forecast — Analyze light schedule with predictions based on inferred lamp schedule."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    DEFAULT_FORECAST_CENTER_DAYS,
    NATURAL_LIGHT_SENSOR,
    TOTAL_LIGHT_SENSOR,
    calculate_daily_dli,
    compute_daily_predicted_dli,
    estimate_hourly_natural_par,
    estimate_remaining_dli,
    fetch_weather_for_range,
    get_model,
    hourly_par_sum_to_dli,
    lamp_hourly_par,
    predict_natural_dli_from_weather,
)
from wp6_data.red.dli import data as dli_data
from wp6_data.red.lamp import RECENT_DAYS, derive_lamp_model
from wp6_data.shared import make_schedule_chart, render_page, render_stat_grid, utc_day_bounds
from wp6_data.shared.time import display_tz

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI Forecast"

@router.get("/forecast", response_class=HTMLResponse)
async def dli_forecast(
    start_date: Annotated[date | None, Query(description="Start date")] = None,
    end_date: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Analyze light schedule with predictions based on inferred lamp schedule."""
    if not dli_data.is_connected():
        return render_page(PAGE_TITLE, "<h1>Database not connected</h1>",
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

    # Get weather client and model
    client = deps.get_weather_client()
    model = get_model()

    # Read the lamps off the two PAR sensors over the recent window. Lamp light
    # is measured during hours the above-lamp sensor sees no daylight, so a
    # greenhouse that is not lighting yields a lamp model that adds nothing and
    # predicted DLI falls back to the natural prediction.
    #
    # Only the *schedule* comes from this fortnight. Attenuation comes from the
    # trained model, which fitted it over its whole training window: a fortnight
    # of winter has no lamp-free daylight to measure it from, and trying gives a
    # ratio above 1 — more light at the canopy than at the roof.
    lamp_window_start, _ = utc_day_bounds(today - timedelta(days=RECENT_DAYS))
    _, lamp_window_end = utc_day_bounds(today)

    try:
        lamp_par_df = await dli_data.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR],
            start=lamp_window_start,
            end=lamp_window_end,
        )
    except Exception as e:
        return render_page(PAGE_TITLE, f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    lamp = None
    if not lamp_par_df.empty:
        lamp = derive_lamp_model(
            lamp_par_df[lamp_par_df["device"] == NATURAL_LIGHT_SENSOR],
            lamp_par_df[lamp_par_df["device"] == TOTAL_LIGHT_SENSOR],
            attenuation=model.attenuation_factor if model.is_trained() else None,
        )
    lamp_schedule = lamp_hourly_par(lamp)

    # Get data for selected date range
    range_start, _ = utc_day_bounds(start_date)
    _, range_end = utc_day_bounds(end_date)

    try:
        par_df = await dli_data.get_par_readings(
            device_ids=[sensor], start=range_start, end=range_end
        )
    except Exception as e:
        return render_page(PAGE_TITLE, f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Prepare actual data for chart (raw readings)
    actual_df = None
    if not par_df.empty:
        actual_df = par_df.rename(columns={"time": "datetime", "value": "par"})

    # Get weather for date range (for predictions)
    predicted_df = None
    natural_df = None

    if model.is_trained():
        try:
            forecasts = await fetch_weather_for_range(client, start_date, end_date)
            daily_natural_dli = predict_natural_dli_from_weather(model, forecasts)

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

                    # Predicted PAR = natural + whatever the lamps actually run at
                    predicted_par = natural_par + lamp_schedule.get(h.datetime.hour, 0.0)
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

    # Yesterday's DLI for the card.
    yesterday_dli = 0.0
    yesterday_natural_dli = 0.0
    try:
        y_start, y_end = utc_day_bounds(yesterday)
        y_par_df = await dli_data.get_par_readings(
            device_ids=[sensor], start=y_start, end=y_end
        )
        if not y_par_df.empty:
            y_daily = calculate_daily_dli(y_par_df)
            if not y_daily.empty:
                yesterday_dli = y_daily["dli"].iloc[0]
            y_weather = await client.get_historical(yesterday, yesterday)
            if y_weather:
                forecast_y = y_weather[0]
                yesterday_natural_dli = model.predict_dli(
                    forecast_y.direct_radiation_sum,
                    diffuse_radiation_sum=forecast_y.diffuse_radiation_sum,
                    cloud_cover_avg=forecast_y.avg_cloud_cover,
                    day_of_year=yesterday.timetuple().tm_yday,
                )
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
            dli = hourly_par_sum_to_dli(grp["par"].sum())
            daily_dli.setdefault(d, {})["predicted"] = dli

    if natural_df is not None and not natural_df.empty:
        natural_df["date"] = natural_df["datetime"].dt.date
        for d, grp in natural_df.groupby("date"):
            dli = hourly_par_sum_to_dli(grp["par"].sum())
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
                    pred_map = compute_daily_predicted_dli(card_fc, nat_map, lamp)
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

    # Convert datetimes from UTC to display timezone for chart rendering
    tz = display_tz()
    for df in (actual_df, predicted_df, natural_df):
        if df is not None and not df.empty and "datetime" in df.columns:
            df["datetime"] = df["datetime"].dt.tz_convert(tz).dt.tz_localize(None)

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
        noon = datetime(d.year, d.month, d.day, 12)
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

    # Say where the lamp half of "predicted" came from — a schedule change is a
    # thing no weather data would catch, so the reader is told what was assumed.
    if lamp is not None and lamp.is_lighting:
        hours = ", ".join(f"{h:02d}:00" for h in sorted(lamp.hours_on))
        lamp_note = (
            f"Total predicted = natural + lamps at {lamp.power_par:.0f} µmol/m²/s "
            f"on {hours} (measured over the last {lamp.observed_days} days; "
            "assumes that schedule continues)."
        )
    elif lamp is not None:
        lamp_note = (
            f"Lamps read as <strong>off</strong> over the last {lamp.observed_days} days, "
            "so predicted equals natural."
        )
    else:
        lamp_note = "No PAR data to read the lamps from; predicted equals natural."

    # Attenuation scales the natural prediction from the roof sensor down to the
    # canopy. When nothing could measure it the page says so rather than letting
    # a fallback of 1.0 read as "no loss".
    if lamp is not None and lamp.attenuation_source == "unknown":
        lamp_note += (
            " <strong>Canopy scaling unknown</strong> — no lamp-free daylight in "
            "this window to measure it from, so natural light is shown at "
            "roof level."
        )

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

    stats_html = render_stat_grid([
        (format_card_value(yesterday_vals), "Yesterday", format_card_sublabel(yesterday_vals)),
        (
            format_card_value(today_vals, use_estimated=True),
            "Today",
            format_card_sublabel(today_vals),
        ),
        (format_card_value(tomorrow_vals), "Tomorrow", format_card_sublabel(tomorrow_vals)),
    ]) + "<small>* predicted ~ estimated</small>"

    content = f"""
        <h1>DLI Forecast</h1>
        {controls_html}
        {stats_html}
        {chart_html}
        <small>
            A/P/N = Actual / Predicted / Natural DLI values per day.<br/>
            Natural light predictions are based on the current ML model.<br/>
            {lamp_note}
        </small>
    """

    return render_page(
        PAGE_TITLE,
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )
