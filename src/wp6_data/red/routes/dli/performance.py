"""GET /dli/performance — Compare predicted DLI with actual sensor readings."""

from datetime import date, timedelta
from typing import Annotated

import numpy as np
import plotly.graph_objects as go
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    DEFAULT_PERFORMANCE_LOOKBACK_DAYS,
    NATURAL_LIGHT_SENSOR,
    PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT,
    PERFORMANCE_ERROR_WARN_THRESHOLD_PCT,
    TOTAL_LIGHT_SENSOR,
    build_lamp_schedules,
    calculate_daily_dli,
    compute_daily_predicted_dli,
    fetch_weather_for_range,
    get_model,
    predict_natural_dli_from_weather,
    try_infer_lamp_from_day,
)
from wp6_data.red.dli import data as dli_data
from wp6_data.shared import render_date_filter, render_page, render_stat_grid, utc_day_bounds

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI Performance"

@router.get("/performance", response_class=HTMLResponse)
async def dli_performance(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Compare predicted DLI (model hindcast) with actual sensor readings."""
    if not dli_data.is_connected():
        return render_page(PAGE_TITLE, "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    model = get_model()
    if not model.is_trained():
        return render_page(
            PAGE_TITLE,
            "<h1>Model not trained</h1><p>Train the prediction model first.</p>",
            show_back_link=True, back_url="/dli",
        )

    # Default to last N days, always exclude today (incomplete)
    today = date.today()
    yesterday = today - timedelta(days=1)
    if start is None:
        start = today - timedelta(days=DEFAULT_PERFORMANCE_LOOKBACK_DAYS)
    if end is None:
        end = yesterday
    end = min(end, yesterday)

    lamp_ref_day = start - timedelta(days=1)
    lamp_ref_dt, _ = utc_day_bounds(lamp_ref_day)
    _, end_dt = utc_day_bounds(end)

    filter_html = render_date_filter(start, end)

    # Fetch actual PAR data for both sensors (include lamp_ref_day for seed)
    try:
        par_df = await dli_data.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=lamp_ref_dt, end=end_dt
        )
    except Exception as e:
        return render_page(PAGE_TITLE, f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Fetch weather data including lamp_ref_day for lamp inference
    client = deps.get_weather_client()
    try:
        forecasts = await fetch_weather_for_range(client, lamp_ref_day, end)
        predicted_natural = predict_natural_dli_from_weather(model, forecasts)
    except Exception as e:
        return render_page(PAGE_TITLE,
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
            if ap < PERFORMANCE_ERROR_WARN_THRESHOLD_PCT:
                bar_colors.append("#22c55e")
            elif ap < PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT:
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
        stats = render_stat_grid([
            (f"{mape:.1f}%", "Avg. Error", "Mean absolute % error"),
            (f"{mae:.2f}", "Avg. Absolute Error", "mol/m²/day off per day"),
            (f"{bias:+.2f}", f"Bias ({bias_lbl})", "Systematic over/under trend"),
        ])

        # Table
        rows = []
        for i, d in enumerate(reversed(shared)):
            idx = len(shared) - 1 - i
            a, p, err, pct = act[idx], pred[idx], errs[idx], pct_errs[idx]
            ap = abs(pct)
            cls = "success" if ap < PERFORMANCE_ERROR_WARN_THRESHOLD_PCT else (
                "warning" if ap < PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT else "error-high"
            )
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
        PAGE_TITLE,
        content,
        extra_css=extra_css,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )
