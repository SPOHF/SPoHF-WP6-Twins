"""GET /monitor/gdd — Growing Degree Day tracker for blueberry harvest prediction."""

from datetime import date, timedelta
from typing import Annotated

import plotly.graph_objects as go
import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.blue.gdd import (
    DEFAULT_BASE_TEMP,
    calculate_daily_gdd,
    cumulative_gdd_from_biofix,
    gdd_from_forecasts,
)
from wp6_data.shared import render_card, render_page
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider
from wp6_data.shared.weather import OpenMeteoClient

log = structlog.get_logger()

router = APIRouter()

SENSOR_TAG = "airTemperature"
DEVICE_NAME = "weatherstation"
PAGE_TITLE = "SPoHF Blue - GDD Tracker"

VARIETY = "Cargo"

# Phenology thresholds — GDD base 0°C accumulated from Jan 1 (European
# convention). Values from private communication; no published Cargo-
# specific data. Ripening thresholds are intentionally absent — calibrate
# locally once observed pick dates are available.
THRESHOLDS = [
    (243, "Bud break (222–265)", "#cc7716"),
    (393, "Shoot flowering (376–409)", "#81ec48"),
    (559, "Peak flowering (552–565)", "#1bbe18"),
    (768, "90% bud break (619–917)", "#0bf5e2"),
    (1200, "Early harvest (?) (1200)", "#2790db"),
    (1500, "Full harvest (?) (1500)", "#1634f9"),
    (1650, "Late harvest (?) (1650)", "#6e179d")
]

# Colors for year traces
YEAR_COLORS = {
    0: "#2563eb",  # current year (blue, primary)
    1: "#9ca3af",  # last year (grey)
    2: "#d1d5db",  # 2 years ago (light grey)
    3: "#e5e7eb",
}

GDD_CSS = """
    .gdd-controls {
        display: flex; gap: 1rem; align-items: end;
        flex-wrap: wrap; margin-bottom: 0.5rem;
    }
    .gdd-controls label { font-size: 0.85rem; }
    .gdd-controls input[type="number"],
    .gdd-controls input[type="date"] {
        padding: 0.3rem 0.5rem; margin: 0;
    }
    .year-toggle {
        display: flex; gap: 0; margin-bottom: 0.5rem;
        border-radius: 6px; overflow: hidden;
        border: 1px solid var(--dashboard-primary);
        width: fit-content;
    }
    .year-btn {
        font-size: 0.8rem; padding: 0.3rem 0.8rem;
        cursor: pointer; border: none; border-radius: 0;
        background: transparent;
        color: var(--dashboard-primary);
        text-decoration: none;
        transition: background 0.15s, color 0.15s;
    }
    .year-btn:not(:last-child) {
        border-right: 1px solid var(--dashboard-primary);
    }
    .year-btn.active {
        background: var(--dashboard-primary); color: #fff;
    }
    .year-btn:not(.active):hover {
        background: color-mix(
            in srgb, var(--dashboard-primary) 12%, transparent);
    }
    .stats-grid { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .stats-grid article {
        flex: 1; min-width: 120px; text-align: center;
        padding: 0.5rem;
    }
    .stat-value { font-size: 1.5rem; font-weight: bold; }
"""


@router.get("/gdd", response_class=HTMLResponse)
async def gdd_tracker(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    year: Annotated[int | None, Query(description="Primary year")] = None,
    base: Annotated[float, Query(
        description="Base temperature °C")] = DEFAULT_BASE_TEMP,
    biofix_month: Annotated[int, Query(
        description="Biofix month (1-12)")] = 1,
    biofix_day: Annotated[int, Query(
        description="Biofix day of month")] = 1,
) -> str:
    """GDD tracker with per-year view and harvest threshold annotations."""

    current_year = date.today().year
    if year is None:
        year = current_year

    biofix_md = (biofix_month, biofix_day)

    # Fetch ALL data once (cheaper than per-year queries)
    try:
        df = await provider.fetch_data(
            sensor_tags=[SENSOR_TAG],
            device_names=[DEVICE_NAME],
        )
    except Exception as e:
        return render_page(
            PAGE_TITLE, f"<h1>Error: {e}</h1>",
            show_back_link=True, back_url="/sensor-monitor",
            data_source=provider.data_source_label)

    if df.empty:
        return render_page(
            PAGE_TITLE,
            "<h1>GDD Tracker</h1>"
            f"<p>No temperature data for {DEVICE_NAME}:{SENSOR_TAG}.</p>",
            show_back_link=True, back_url="/sensor-monitor", extra_css=GDD_CSS,
            data_source=provider.data_source_label)

    # Calculate daily GDD for ALL data
    daily_all = calculate_daily_gdd(df, base_temp=base)

    # Determine which years actually have data
    daily_all["year"] = [d.year for d in daily_all["date"]]
    available_years = sorted(daily_all["year"].unique(), reverse=True)

    # Per-year GDD curves (from biofix within each year)
    # display_date maps all years onto the primary year's calendar
    # so the x-axis shows real dates while years still align.
    try:
        primary_biofix = date(year, *biofix_md)
    except ValueError:
        primary_biofix = date(year, 1, 1)

    year_curves: dict[int, dict] = {}
    for y in available_years:
        try:
            bf = date(y, *biofix_md)
        except ValueError:
            continue
        year_daily = cumulative_gdd_from_biofix(daily_all, bf)
        year_daily = year_daily[
            year_daily["date"] < date(y + 1, 1, 1)
        ]
        if not year_daily.empty:
            bf_ordinal = bf.toordinal()
            year_daily = year_daily.copy()
            year_daily["doy"] = [
                (d.toordinal() - bf_ordinal)
                for d in year_daily["date"]
            ]
            # Map onto primary year's calendar for aligned display
            year_daily["display_date"] = [
                primary_biofix + timedelta(days=doy)
                for doy in year_daily["doy"]
            ]
            year_curves[y] = {
                "df": year_daily,
                "total": year_daily["cumulative_gdd"].iloc[-1],
                "days": len(year_daily),
                "avg": year_daily["daily_gdd"].mean(),
            }

    # Forecast for primary year (only if it's current year)
    forecast_df = None
    predicted_total = None
    if year == current_year and year in year_curves:
        try:
            weather = OpenMeteoClient()
            forecasts = await weather.get_forecast(days=14)
            primary = year_curves[year]["df"]
            if forecasts and not primary.empty:
                last_actual = primary["date"].iloc[-1]
                future = [
                    f for f in forecasts if f.date > last_actual
                ]
                if future:
                    cum_start = primary["cumulative_gdd"].iloc[-1]
                    forecast_df = gdd_from_forecasts(
                        future, base_temp=base,
                        cumulative_start=cum_start,
                    )
                    bf = date(year, *biofix_md)
                    bf_ord = bf.toordinal()
                    forecast_df = forecast_df.copy()
                    forecast_df["doy"] = [
                        (d.toordinal() - bf_ord)
                        for d in forecast_df["date"]
                    ]
                    forecast_df["display_date"] = [
                        primary_biofix + timedelta(days=doy)
                        for doy in forecast_df["doy"]
                    ]
                    predicted_total = forecast_df[
                        "cumulative_gdd"
                    ].iloc[-1]
            await weather.close()
        except Exception:
            log.warning("gdd_forecast_failed", exc_info=True)

    # --- Build page ---
    primary_data = year_curves.get(year, {})
    total_gdd = primary_data.get("total", 0)
    days_count = primary_data.get("days", 0)
    avg_daily = primary_data.get("avg", 0)

    # Year toggle
    year_toggle = _year_toggle_html(
        available_years, year, base, biofix_md)

    # Controls
    controls = _controls_html(base, biofix_md, year)

    # Stats
    pred_card = ""
    if predicted_total is not None:
        pred_card = f"""
            <article>
                <div class="stat-value">{predicted_total:.0f} °C·d</div>
                <small>Predicted +14d</small>
            </article>"""

    stats_html = f"""
        <div class="stats-grid">
            <article>
                <div class="stat-value">{total_gdd:.0f} °C·d</div>
                <small>Cumulative GDD ({year})</small>
            </article>
            {pred_card}
            <article>
                <div class="stat-value">{days_count}</div>
                <small>Days since biofix</small>
            </article>
            <article>
                <div class="stat-value">{avg_daily:.1f} °C·d</div>
                <small>Avg daily GDD</small>
            </article>
        </div>"""

    # Chart
    chart_html = _build_chart(
        year, year_curves, forecast_df, base, biofix_md)

    # Data table for primary year
    table_html = _build_table(year_curves.get(year, {}).get("df"))

    formula_html = f"""
        <code>Daily GDD = max(0, (T<sub>max</sub> + T<sub>min</sub>)
        / 2 &minus; {base}°C)</code><br>
        <small>Each day's GDD (in °C·d) is the average temperature
        minus the base, clamped to zero. Accumulated from biofix
        (default: Jan 1, European convention).
        </small>
    """

    content = f"""
        <h1>GDD Tracker — {VARIETY}</h1>
        {year_toggle}
        {controls}
        {render_card("How GDD works", formula_html)}
        {render_card("Summary", stats_html)}
        {chart_html}
        {render_card("Daily GDD — " + str(year), table_html)}
    """

    return render_page(
        PAGE_TITLE, content,
        show_back_link=True, back_url="/sensor-monitor", extra_css=GDD_CSS,
        data_source=provider.data_source_label)


def _year_toggle_html(
    available: list[int],
    primary: int,
    base: float,
    biofix_md: tuple[int, int],
) -> str:
    """Render year selection toggle buttons."""
    buttons = []
    for y in available:
        active = "active" if y == primary else ""
        params = (
            f"?year={y}&base={base}"
            f"&biofix_month={biofix_md[0]}"
            f"&biofix_day={biofix_md[1]}"
        )
        buttons.append(
            f'<a href="/sensor-monitor/gdd{params}" class="year-btn {active}">'
            f'{y}</a>')

    return f'<div class="year-toggle">{"".join(buttons)}</div>'


def _controls_html(
    base: float,
    biofix_md: tuple[int, int],
    year: int,
) -> str:
    """Render base temp and biofix controls."""
    return f"""
        <form method="get" class="gdd-controls">
            <input type="hidden" name="year" value="{year}">
            <div>
                <label for="base">Base temp (°C)</label>
                <input type="number" id="base" name="base"
                    value="{base}" step="0.1" min="0" max="20">
            </div>
            <div>
                <label for="biofix_month">Biofix month</label>
                <input type="number" id="biofix_month"
                    name="biofix_month"
                    value="{biofix_md[0]}" min="1" max="12">
            </div>
            <div>
                <label for="biofix_day">Biofix day</label>
                <input type="number" id="biofix_day"
                    name="biofix_day"
                    value="{biofix_md[1]}" min="1" max="31">
            </div>
            <small style="align-self:center;opacity:0.7">
                GDD accumulation start</small>
            <button type="submit">Update</button>
        </form>
    """


def _build_chart(
    primary_year: int,
    year_curves: dict[int, dict],
    forecast_df,
    base: float,
    biofix_md: tuple[int, int],
) -> str:
    """Build the cumulative GDD chart with year overlays and thresholds."""
    if not year_curves:
        return ""

    fig = go.Figure()

    # Add comparison years first (behind primary)
    for y, data in sorted(
        year_curves.items(), reverse=True
    ):
        df = data["df"]
        is_primary = y == primary_year
        age = 0 if is_primary else (primary_year - y)
        color = YEAR_COLORS.get(age, "#e5e7eb")

        if is_primary:
            continue  # drawn last

        fig.add_trace(go.Scatter(
            x=df["display_date"], y=df["cumulative_gdd"],
            name=str(y), mode="lines",
            line={"color": color, "width": 1.5},
            customdata=df["date"].astype(str).tolist(),
            hovertemplate=(
                f"<b>{y}:</b> %{{customdata}}<br>"
                "GDD: %{y:.0f}<extra></extra>"),
        ))

    # Primary year
    if primary_year in year_curves:
        df = year_curves[primary_year]["df"]
        color = YEAR_COLORS[0]
        fig.add_trace(go.Scatter(
            x=df["display_date"], y=df["cumulative_gdd"],
            name=str(primary_year), mode="lines",
            fill="tozeroy",
            fillcolor="rgba(37, 99, 235, 0.15)",
            line={"color": color, "width": 2.5},
            customdata=list(zip(
                df["date"].astype(str),
                df["daily_gdd"],
                df["t_min"], df["t_max"],
                strict=True,
            )),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Cumulative: %{y:.0f} GDD<br>"
                "Daily: %{customdata[1]:.1f} GDD<br>"
                "Min: %{customdata[2]:.1f}°C"
                "  Max: %{customdata[3]:.1f}°C"
                "<extra></extra>"),
        ))

    # Forecast extension
    if forecast_df is not None and not forecast_df.empty:
        primary_df = year_curves[primary_year]["df"]
        last_disp = primary_df["display_date"].iloc[-1]
        last_gdd = primary_df["cumulative_gdd"].iloc[-1]
        bridge_x = [last_disp] + forecast_df[
            "display_date"].tolist()
        bridge_gdd = [last_gdd] + forecast_df[
            "cumulative_gdd"].tolist()
        fig.add_trace(go.Scatter(
            x=bridge_x, y=bridge_gdd,
            name="Forecast", mode="lines",
            line={"color": "#f97316", "width": 2,
                  "dash": "dash"},
            customdata=(
                [""] + forecast_df["date"].astype(str).tolist()
            ),
            hovertemplate=(
                "<b>Forecast</b> %{customdata}<br>"
                "Predicted: %{y:.0f} GDD"
                "<extra></extra>"),
        ))

    for gdd_val, label, color in THRESHOLDS:
        fig.add_hline(
            y=gdd_val, line_dash="dot", line_width=1,
            line_color=color,
            annotation_text=label,
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color=color,
        )

    biofix_label = f"{biofix_md[1]}/{biofix_md[0]}"
    fig.update_layout(
        template="plotly_white",
        title=f"{VARIETY} — Cumulative GDD (base {base}°C, biofix {biofix_label})",
        yaxis_title="GDD (°C·d)",
        xaxis={"type": "date", "tickformat": "%b %d"},
        height=500,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom",
                "y": 1.02, "xanchor": "right", "x": 1},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def _build_table(df) -> str:
    """Build the daily GDD HTML table."""
    if df is None or df.empty:
        return "<p>No data.</p>"

    rows = ""
    for _, row in df.iterrows():
        rows += f"""
            <tr>
                <td>{row['date']}</td>
                <td>{row['t_min']:.1f}</td>
                <td>{row['t_max']:.1f}</td>
                <td>{row['daily_gdd']:.1f}</td>
                <td>{row['cumulative_gdd']:.0f}</td>
            </tr>"""

    return f"""
        <table>
            <thead><tr>
                <th>Date</th><th>Min °C</th><th>Max °C</th>
                <th>Daily GDD</th><th>Cumulative</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>"""
