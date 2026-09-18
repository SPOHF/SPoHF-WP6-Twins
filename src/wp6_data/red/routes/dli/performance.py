"""GET /dli/performance — Compare predicted DLI with actual sensor readings.

Which comparison is shown is a query parameter, not a client-side toggle, so a
particular view is a URL somebody can link to. It also means each request builds
one comparison rather than both: the two modes need different predictions and
different sensor data, and only the total mode needs the lamp schedule at all.
"""

from datetime import date, timedelta
from typing import Annotated

import numpy as np
import plotly.graph_objects as go
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import (
    DEFAULT_PERFORMANCE_LOOKBACK_DAYS,
    MIN_INDOOR_PAR,
    NATURAL_LIGHT_SENSOR,
    PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT,
    PERFORMANCE_ERROR_WARN_THRESHOLD_PCT,
    TOTAL_LIGHT_SENSOR,
    calculate_daily_dli,
    compute_daily_predicted_dli,
    fetch_weather_for_range,
    get_model,
    par_sum_to_dli,
    predict_natural_dli_from_weather,
)
from wp6_data.red.dli import data as dli_data
from wp6_data.red.lamp import RECENT_DAYS, derive_lamp_model
from wp6_data.shared import (
    pill_row,
    render_date_filter,
    render_page,
    render_stat_grid,
    utc_day_bounds,
)

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI Performance"

# The two comparisons this page offers. They are not two views of one number:
# total light is measured *under* the lamps and natural light *above* them, so
# each mode has its own actual sensor and its own prediction. Naming the sensor
# position in the label is deliberate — `NATURAL_LIGHT_SENSOR` is called
# "Natural Light" but hangs above the lamps, and conflating that with
# natural light at plant level is exactly how this page came to score an
# attenuated prediction against an un-attenuated sensor.
TOTAL_MODE = "total"
NATURAL_MODE = "natural"
MODE_LABELS = {
    TOTAL_MODE: "Total (under lamps)",
    NATURAL_MODE: "Natural (above lamps)",
}
DEFAULT_MODE = TOTAL_MODE

BASE_PATH = "/dli/performance"

# Below this the sensor did not really report, and the day is not scored.
#
# `calculate_daily_dli` still returns a row for a day of flat zeros — red's PAR
# sensors read zero for six weeks in 2026 — and a zero actual is not a dark day,
# it is an absent one. Scoring against it measures the outage twice over: the
# percentage error is undefined, and the absolute error is the whole prediction.
#
# The bar is the gate training already uses, expressed as a DLI. A day the model
# would not have learned from does not get to judge it either, and reusing the
# threshold means the two cannot drift apart.
NO_DATA_DLI = par_sum_to_dli(MIN_INDOOR_PAR)


def _runs(days: list[date]) -> list[tuple[date, date]]:
    """Consecutive dates collapsed into (first, last) spans.

    An outage is one period, not forty-six separate marks; shading it as a span
    is what distinguishes "the sensor was off for six weeks" from "these days
    happen to be missing".
    """
    spans: list[tuple[date, date]] = []
    for day in sorted(days):
        if spans and day - spans[-1][1] == timedelta(days=1):
            spans[-1] = (spans[-1][0], day)
        else:
            spans.append((day, day))
    return spans


def _page(body: str) -> str:
    """This page's shell. Every exit renders the same frame, error or not."""
    return render_page(
        PAGE_TITLE, body, extra_css=EXTRA_CSS,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/dli",
    )


@router.get("/performance", response_class=HTMLResponse)
async def dli_performance(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
    mode: Annotated[
        str,
        Query(description="Which comparison to show (total/natural); defaults to total"),
    ] = DEFAULT_MODE,
) -> str:
    """Compare predicted DLI (model hindcast) with actual sensor readings."""
    if mode not in MODE_LABELS:
        mode = DEFAULT_MODE

    if not dli_data.is_connected():
        return _page("<h1>Database not connected</h1>")

    model = get_model()
    if not model.is_trained():
        return _page(
            "<h1>Model not trained</h1><p>Train the prediction model first.</p>"
        )

    # Default to last N days, always exclude today (incomplete)
    today = date.today()
    yesterday = today - timedelta(days=1)
    if start is None:
        start = today - timedelta(days=DEFAULT_PERFORMANCE_LOOKBACK_DAYS)
    if end is None:
        end = yesterday
    end = min(end, yesterday)

    start_dt, _ = utc_day_bounds(start)
    _, end_dt = utc_day_bounds(end)

    filter_html = render_date_filter(start, end, {"mode": mode})
    toggle_html = pill_row(
        BASE_PATH, "mode", list(MODE_LABELS.items()), mode,
        {"start": start.isoformat(), "end": end.isoformat()}, "View",
    )
    header = f"<h1>DLI Performance</h1>{filter_html}{toggle_html}"

    is_total = mode == TOTAL_MODE
    sensor = TOTAL_LIGHT_SENSOR if is_total else NATURAL_LIGHT_SENSOR

    try:
        par_df = await dli_data.get_par_readings(
            device_ids=[sensor], start=start_dt, end=end_dt
        )
    except Exception as e:
        return _page(header + f"<h1>Error: {e}</h1>")

    # Only the total comparison adds the lamps. The schedule is read from the
    # fortnight *before* the scored window, so this hindcasts with only what was
    # knowable on day one — the same "recent schedule continues" assumption the
    # forecast page makes. Attenuation is not read from that fortnight; see
    # derive_lamp_model on why a short winter window cannot identify it.
    lamp = None
    if is_total:
        lamp_window_start, _ = utc_day_bounds(start - timedelta(days=RECENT_DAYS))
        _, lamp_window_end = utc_day_bounds(start - timedelta(days=1))
        try:
            lamp_par_df = await dli_data.get_par_readings(
                device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR],
                start=lamp_window_start, end=lamp_window_end,
            )
        except Exception as e:
            return _page(header + f"<h1>Error: {e}</h1>")
        if not lamp_par_df.empty:
            lamp = derive_lamp_model(
                lamp_par_df[lamp_par_df["device"] == NATURAL_LIGHT_SENSOR],
                lamp_par_df[lamp_par_df["device"] == TOTAL_LIGHT_SENSOR],
                attenuation=model.attenuation_factor,
            )

    client = deps.get_weather_client()
    try:
        forecasts = await fetch_weather_for_range(client, start, end)
        # Total is scored against the under-lamp sensor, so its natural half must
        # be carried down to plant level before the lamps are added. Natural is
        # scored against the above-lamp sensor, which attenuation has not touched
        # — asking for the matching position is what keeps the comparison
        # like-for-like.
        predicted_natural = predict_natural_dli_from_weather(
            model, forecasts, at_plant_level=is_total
        )
    except Exception as e:
        return _page(header + f"<h1>Weather data error: {e}</h1>")

    # Calculate actual DLI per day (filter to requested range only)
    actual_dli: dict[date, float] = {}
    if not par_df.empty:
        daily_df = calculate_daily_dli(par_df)
        for _, row in daily_df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            if d < start or d > end or row["device"] != sensor:
                continue
            actual_dli[d] = row["dli"]

    range_forecasts = [f for f in forecasts if start <= f.date <= end]
    predicted_natural_range = {d: v for d, v in predicted_natural.items() if start <= d <= end}
    predicted_dli = (
        compute_daily_predicted_dli(range_forecasts, predicted_natural_range, lamp)
        if is_total
        else predicted_natural_range
    )

    label = MODE_LABELS[mode]
    actual_name = f"Actual {label}"
    predicted_name = f"Predicted {label}"

    shared = sorted(set(actual_dli) & set(predicted_dli))
    if not shared:
        return _page(header + "<p>No overlapping data for this view.</p>")

    # Charts show every overlapping day, so an outage stays visible; only the
    # days the sensor actually reported are scored. See NO_DATA_DLI.
    scored = [d for d in shared if actual_dli[d] > NO_DATA_DLI]
    no_data = [d for d in shared if actual_dli[d] <= NO_DATA_DLI]
    if not scored:
        return _page(
            header + f"<p>None of these {len(shared)} days carry usable readings "
            f"from <code>{sensor}</code> — every actual DLI is at or below "
            f"{NO_DATA_DLI:.2f} mol/m²/day, which means the sensor was off "
            f"rather than the sky dark.</p>"
        )

    pred = [predicted_dli[d] for d in shared]

    scored_act = [actual_dli[d] for d in scored]
    scored_pred = [predicted_dli[d] for d in scored]
    scored_errs = [p - a for a, p in zip(scored_act, scored_pred, strict=True)]
    scored_pct = [
        (p - a) / a * 100 for a, p in zip(scored_act, scored_pred, strict=True)
    ]
    pct_by_day = dict(zip(scored, scored_pct, strict=True))

    mape = float(np.mean([abs(e) for e in scored_pct]))
    mae = float(np.mean([abs(e) for e in scored_errs]))
    bias = float(np.mean(scored_errs))

    # Line chart.
    #
    # An unscored day is drawn as a BREAK in the actual line, never as a zero.
    # Plotting 0.0 asserts that the sensor measured no light, which is a claim
    # about the greenhouse; a gap says only that nothing was measured. Over
    # red's six-week 2026 outage the difference is the whole chart — 46 days of
    # flat zero against a ~30 mol prediction reads as a broken model rather
    # than an absent sensor.
    was_scored = set(scored)
    actual_line = [actual_dli[d] if d in was_scored else None for d in shared]

    fig_cmp = go.Figure()
    fig_cmp.add_trace(go.Scatter(
        x=shared, y=pred,
        name=predicted_name, mode="lines+markers",
        line={"color": "#e74c3c", "width": 2, "dash": "dash"}, marker={"size": 6},
        hovertemplate="%{y:.1f}<extra></extra>",
    ))
    # `tonexty` fills to the trace above, and breaks wherever either side is
    # None — so the band disappears across a gap instead of spanning it.
    fig_cmp.add_trace(go.Scatter(
        x=shared, y=actual_line,
        name=actual_name, mode="lines+markers",
        line={"color": "#3498db", "width": 2}, marker={"size": 6},
        fill="tonexty", fillcolor="rgba(231, 76, 60, 0.1)",
        hovertemplate="%{y:.1f}<extra></extra>",
    ))
    for first, last in _runs(no_data):
        # Half-day padding so a single excluded day is still a visible band.
        fig_cmp.add_vrect(
            x0=first - timedelta(hours=12), x1=last + timedelta(hours=12),
            fillcolor="#94a3b8", opacity=0.18, line_width=0, layer="below",
            annotation_text="no sensor data" if (last - first).days >= 2 else None,
            annotation_position="top left",
            annotation_font={"size": 10, "color": "#64748b"},
        )
    fig_cmp.update_layout(
        title=f"Actual vs Predicted — {label}",
        yaxis_title="DLI (mol/m²/day)", height=400, hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02,
                "xanchor": "right", "x": 1},
        margin={"t": 60, "b": 40},
    )
    chart_cmp = fig_cmp.to_html(full_html=False, include_plotlyjs="cdn")

    # Error bar chart
    bar_colors = []
    for pct in scored_pct:
        ap = abs(pct)
        if ap < PERFORMANCE_ERROR_WARN_THRESHOLD_PCT:
            bar_colors.append("#22c55e")
        elif ap < PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT:
            bar_colors.append("#f59e0b")
        else:
            bar_colors.append("#ef4444")

    fig_err = go.Figure()
    fig_err.add_trace(go.Bar(
        x=scored, y=scored_errs, marker_color=bar_colors,
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
    tiles = [
        (f"{mape:.1f}%", "Avg. Error", f"Mean absolute % error over {len(scored)} days"),
        (f"{mae:.2f}", "Avg. Absolute Error", "mol/m²/day off per day"),
        (f"{bias:+.2f}", f"Bias ({bias_lbl})", "Systematic over/under trend"),
    ]
    if no_data:
        tiles.append(
            (str(len(no_data)), "Days Not Scored", f"No reading from {sensor}")
        )
    stats = render_stat_grid(tiles)

    # Table
    rows = []
    for d in reversed(shared):
        a, p = actual_dli[d], predicted_dli[d]
        pct = pct_by_day.get(d)
        if pct is None:
            # Not an error of 0% — an absent measurement. Saying so is the whole
            # point; the old page showed these as a perfect day.
            cell = '<td class="no-data">no data</td>'
        else:
            ap = abs(pct)
            cls = "success" if ap < PERFORMANCE_ERROR_WARN_THRESHOLD_PCT else (
                "warning" if ap < PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT else "error-high"
            )
            cell = f'<td class="{cls}">{pct:+.1f}%</td>'
        rows.append(f"""<tr>
            <td>{d}</td><td>{a:.2f}</td><td>{p:.2f}</td>
            <td>{p - a:+.2f}</td>{cell}
        </tr>""")

    table = f"""
        <details>
            <summary>View Data Table ({len(shared)} days, {len(scored)} scored)</summary>
            <table><thead><tr>
                <th>Date</th><th>{actual_name}</th><th>{predicted_name}</th>
                <th>Error</th><th>Error %</th>
            </tr></thead><tbody>{''.join(rows)}</tbody></table>
        </details>
    """

    content = f"""
        {header}
        <p>Comparing model predictions with <code>{sensor}</code>.</p>
        {stats}
        <div class="chart-section">{chart_cmp}</div>
        <div class="chart-section">{chart_err}</div>
        {table}
    """

    return _page(content)


# The toggle needs no styling of its own: `pill_row` reuses the shared
# .group-toggle / .group-btn rules the chart pages already ship.
EXTRA_CSS = """
    .chart-section { margin-bottom: 30px; }
    td, th { text-align: center; }
    .error-high { color: #ef4444 !important; font-weight: bold; }
    .no-data { color: #94a3b8 !important; font-style: italic; }
"""
