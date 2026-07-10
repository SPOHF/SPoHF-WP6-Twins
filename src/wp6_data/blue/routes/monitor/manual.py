"""Manual monitor hub and permanent long_data dashboards."""

from datetime import UTC, datetime
from typing import Annotated

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.blue.long_data import (
    MEASURE_LABELS,
    MEASURE_MAP,
    MEASURE_UNITS,
)
from wp6_data.blue.treatments import (
    LONG_DATA_TREATMENT_MAP as _LONG_DATA_TREATMENT_MAP,
)
from wp6_data.blue.treatments import (
    TREATMENT_ORDER,
    treatment_color,
)
from wp6_data.shared import render_hub_card, render_hub_grid, render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter(dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "SPoHF Blue - Manual Monitor"
YEAR_START = datetime(2024, 1, 1, tzinfo=UTC)
YEAR_END = datetime(2026, 1, 1, tzinfo=UTC)
YEARS: tuple[int, ...] = (2024, 2025)

# Device names used by long_data ingest are canonical treatment codes.
_LONG_DATA_DEVICES: frozenset[str] = frozenset(_LONG_DATA_TREATMENT_MAP.values())

# All sensor tags that long_data ingest can produce.
_ALL_LONG_DATA_SENSORS: list[str] = sorted(frozenset(MEASURE_MAP.values()))

# Preferred display order for measures.
_MEASURE_DISPLAY_ORDER: tuple[str, ...] = (
    "shoot_length",
    "yield_per_plant",
    "brix",
    "brix_after_storage",
    "firmness",
    "firmness_after_storage",
    "berry_weight",
    "berry_weight_after_storage",
    "sample_weight_before_storage",
    "sample_weight_after_storage",
    "score",
    "budscore",
    "flowering_score",
)

# 2025 correlation focus: core quality metrics + score dimensions.
_CORR_2025_MEASURE_ORDER: tuple[str, ...] = (
    "shoot_length",
    "yield_per_plant",
    "brix",
    "firmness",
    "berry_weight",
    "score",
    "budscore",
    "flowering_score",
)

@router.get("/manual-monitor", response_class=HTMLResponse)
async def manual_home() -> str:
    """Manual monitor hub page."""
    content = f"""
        <h1>Manual Monitor</h1>
        <p>Permanent dashboards based on uploaded long_data measurements.</p>

        {render_hub_grid([
            render_hub_card(
                "Measure Comparison",
                "Year-by-year treatment box plots for measures that are present "
                "in both 2024 and 2025.",
                href="/manual-monitor/measure-comparison",
                label="View Measure Comparison",
            ),
            render_hub_card(
                "Correlation Matrix (2025)",
                "Pearson heatmap for 2025, including Score/Bud score/Flowering "
                "score where available.",
                href="/manual-monitor/correlation",
                label="View Correlation Matrix",
            ),
        ])}
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)


@router.get("/manual-monitor/measure-comparison", response_class=HTMLResponse)
async def measure_comparison(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """Manual long_data treatment box plots for comparable measures."""
    df, comparable, error = await _load_long_data(provider)
    if error is not None:
        return error

    assert df is not None
    assert comparable is not None
    df_cmp = df[df["sensor"].isin(comparable)]
    include_js = True
    cards: list[str] = []
    for sensor in comparable:
        card_html, include_js = _render_measure_card(df_cmp, sensor, include_js=include_js)
        if card_html:
            cards.append(card_html)
    measure_cards = "".join(cards)

    content = f"""
        <h1>Measure Comparison</h1>
        <p>
            One treatment-comparison box plot per year for each measure that
            appears in both 2024 and 2025.
        </p>
        {measure_cards}
    """
    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True,
        back_url="/manual-monitor",
    )


@router.get("/manual-monitor/correlation", response_class=HTMLResponse)
async def correlation_2025(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """2025-only long_data correlation heatmap, including score dimensions."""
    df, _, error = await _load_long_data(provider)
    if error is not None:
        return error

    assert df is not None
    df_2025 = df[df["year"] == 2025]
    if df_2025.empty:
        return render_page(
            PAGE_TITLE,
            "<h1>Correlation Matrix (2025)</h1><p>No 2025 long_data rows found.</p>",
            show_back_link=True,
            back_url="/manual-monitor",
        )

    available = [m for m in _CORR_2025_MEASURE_ORDER if m in set(df_2025["sensor"])]
    corr_html, nan_report_html = _build_correlation_heatmap_2025(df_2025, available)
    content = f"""
        <h1>Correlation Matrix (2025)</h1>
        <p>
            Pearson correlations across treatment-level seasonal means for 2025,
            including score-type measures where present.
        </p>
        {render_correlation_explanation()}
        <article>
            {corr_html}
        </article>
        {nan_report_html}
    """
    return render_page(
        PAGE_TITLE,
        content,
        show_back_link=True,
        back_url="/manual-monitor",
    )


async def _load_long_data(
    provider: SensorDataProvider,
) -> tuple[pd.DataFrame | None, list[str] | None, str | None]:
    """Fetch and scope long_data rows from provider.fetch_data.

    Returns ``(df, comparable_measures, error_html)``.
    """
    try:
        df = await provider.fetch_data(
            sensor_tags=_ALL_LONG_DATA_SENSORS,
            device_names=sorted(_LONG_DATA_DEVICES),
            start=YEAR_START,
            end=YEAR_END,
        )
    except Exception as e:
        return None, None, render_page(
            PAGE_TITLE,
            f"<p>Error fetching data: {e}</p>",
            show_back_link=True,
            back_url="/manual-monitor",
        )

    if df.empty:
        return None, None, render_page(
            PAGE_TITLE,
            "<h1>Manual Monitor</h1><p>No data found for 2024-2025.</p>",
            show_back_link=True,
            back_url="/manual-monitor",
        )

    df = df.copy()
    # Scope by known long_data devices; keeps provider fetch_data schema stable.
    df = df[df["device"].isin(_LONG_DATA_DEVICES)]

    df["year"] = df["time"].dt.year
    df = df[df["year"].isin(YEARS)]
    if df.empty:
        return None, None, render_page(
            PAGE_TITLE,
            "<h1>Manual Monitor</h1><p>No long_data rows in 2024-2025.</p>",
            show_back_link=True,
            back_url="/manual-monitor",
        )

    comparable = _find_comparable_measures(df)
    if not comparable:
        return None, None, render_page(
            PAGE_TITLE,
            "<h1>Manual Monitor</h1><p>No measures shared by 2024 and 2025.</p>",
            show_back_link=True,
            back_url="/manual-monitor",
        )
    return df, comparable, None


def _find_comparable_measures(df: pd.DataFrame) -> list[str]:
    """Return sensor tags present in both 2024 and 2025, in display order."""
    by_year = df.groupby("year")["sensor"].apply(frozenset)
    shared = frozenset.intersection(*by_year.values) if len(by_year) >= 2 else frozenset()
    ordered = [m for m in _MEASURE_DISPLAY_ORDER if m in shared]
    ordered += sorted(shared - set(_MEASURE_DISPLAY_ORDER))
    return ordered


def _measure_axis_label(sensor: str) -> str:
    label = MEASURE_LABELS.get(sensor, sensor.replace("_", " ").title())
    unit = MEASURE_UNITS.get(sensor)
    return f"{label} ({unit})" if unit else label


def _render_measure_card(
    df: pd.DataFrame,
    sensor: str,
    *,
    include_js: bool,
) -> tuple[str, bool]:
    sensor_df = df[df["sensor"] == sensor].copy()
    if sensor_df.empty:
        return "", include_js

    sensor_df["treatment"] = sensor_df["device"]
    include_for_next = include_js
    plots: list[str] = []
    for year in YEARS:
        year_html = _build_year_boxplot(sensor_df, sensor, year, include_js=include_for_next)
        if year_html:
            plots.append(year_html)
            include_for_next = False
    plot_html = "".join(plots)
    if not plot_html:
        return "", include_js

    return f"""
        <article>
            <h3>{_measure_axis_label(sensor)}</h3>
            {plot_html}
        </article>
    """, include_for_next


def render_correlation_explanation() -> str:
    """Collapsible 'how to read a correlation matrix' block, reusable across pages."""
    return """
        <details style="margin-bottom:1rem">
          <summary><strong>How to read a correlation matrix</strong></summary>
          <div style="padding:0.75rem 0 0.25rem">
            <p>
              A correlation matrix shows the <strong>correlation coefficient</strong>
              (typically Pearson <strong>r</strong> or Spearman <strong>ρ</strong>)
              between every pair of variables. Each cell holds a value between
              <strong>&minus;1</strong> and <strong>+1</strong>:
            </p>
            <ul>
              <li><strong>r/ρ = +1</strong> — perfect positive relationship: when one
                variable rises the other rises by a proportional amount.</li>
              <li><strong>r/ρ = &minus;1</strong> — perfect negative (inverse)
                relationship.</li>
              <li><strong>r/ρ = 0</strong> — no linear relationship.</li>
              <li>Values near <strong>&plusmn;0.3</strong> are often considered weak,
                <strong>&plusmn;0.5</strong> moderate, and <strong>&plusmn;0.7</strong>
                strong, though thresholds depend on the domain.</li>
            </ul>
            <p>
              The matrix is <em>symmetric</em>: the cell at row A / column B is
              identical to row B / column A. The diagonal is always 1 (a variable
              is perfectly correlated with itself). Colour encodes direction and
              strength: red tones indicate positive correlation, blue tones
              indicate negative. Cells marked <strong>NaN</strong> mean there
              were not enough overlapping, non-constant observations to compute
              a coefficient.
            </p>
          </div>
        </details>
    """


def _build_year_boxplot(
    sensor_df: pd.DataFrame,
    sensor: str,
    year: int,
    *,
    include_js: bool,
) -> str:
    year_df = sensor_df[sensor_df["year"] == year]
    if year_df.empty:
        return ""

    present_treatments = [t for t in TREATMENT_ORDER if t in set(year_df["treatment"])]
    if not present_treatments:
        present_treatments = sorted(set(year_df["treatment"]))

    y_label = _measure_axis_label(sensor)
    fig = go.Figure()
    for treatment in present_treatments:
        tdf = year_df[year_df["treatment"] == treatment]
        fig.add_trace(
            go.Box(
                x=[treatment] * len(tdf),
                y=tdf["value"],
                name=treatment,
                marker_color=treatment_color(treatment),
                boxpoints="outliers",
                jitter=0.35,
                pointpos=0,
                showlegend=False,
                hovertemplate=(
                    f"<b>{treatment}</b><br>"
                    f"Year: {year}<br>"
                    f"{y_label}: %{{y:.3f}}"
                    "<extra></extra>"
                ),
            ),
        )

    counts_parts = [
        f'<span style="color:{treatment_color(t)};font-weight:600">{t}</span>: '
        f'{len(year_df[year_df["treatment"] == t])}'
        for t in present_treatments
    ]
    counts_html = (
        '<p style="font-size:0.82rem;margin:0 0 0.25rem">'
        f'data points &mdash; {" &nbsp;&middot;&nbsp; ".join(counts_parts)}'
        "</p>"
    )

    fig.update_layout(
        template="plotly_white",
        height=380,
        margin={"l": 40, "r": 20, "t": 45, "b": 60},
        title=f"{y_label} ({year})",
        xaxis={
            "title": "Fertilizer strategy",
            "categoryorder": "array",
            "categoryarray": present_treatments,
        },
        yaxis={"title": y_label},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    plot_html = fig.to_html(full_html=False, include_plotlyjs="cdn" if include_js else False)
    return counts_html + plot_html


def _build_correlation_heatmap_2025(
    df: pd.DataFrame, measures: list[str],
) -> tuple[str, str]:
    """Pearson correlation heatmap over 2025 treatment-level seasonal means."""
    if len(measures) < 2:
        return (
            "<p>Not enough 2025 measures to build a correlation matrix.</p>",
            "",
        )

    seasonal = (
        df.groupby(["device", "sensor"])["value"]
        .mean()
        .reset_index()
    )
    wide = seasonal.pivot_table(
        index=["device"],
        columns="sensor",
        values="value",
        aggfunc="mean",
    ).reset_index()

    available = [m for m in measures if m in wide.columns]
    if len(available) < 2:
        return (
            "<p>Not enough overlapping 2025 measures to compute correlations.</p>",
            "",
        )

    corr = wide[available].corr()
    labels = [_measure_axis_label(m) for m in available]
    z = corr.values.tolist()

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=labels,
            y=labels,
            colorscale="RdBu",
            reversescale=True,
            zmin=-1,
            zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in z],
            texttemplate="%{text}",
            textfont={"size": 12},
            hovertemplate="X: %{x}<br>Y: %{y}<br>r = %{z:.3f}<extra></extra>",
        ),
    )
    fig.update_layout(
        template="plotly_white",
        height=max(400, 150 + len(available) * 60),
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return (
        fig.to_html(full_html=False, include_plotlyjs="cdn"),
        _render_nan_diagnostics(available, wide, corr),
    )


def _render_nan_diagnostics(
    measures: list[str],
    wide: pd.DataFrame,
    corr: pd.DataFrame,
) -> str:
    """Explain NaN correlation cells with overlap/variance diagnostics."""
    notna = wide[measures].notna().astype(int)
    overlap = notna.T.dot(notna)
    stdev = wide[measures].std(skipna=True)

    rows: list[str] = []
    for i, left in enumerate(measures):
        for right in measures[i + 1:]:
            if pd.notna(corr.loc[left, right]):
                continue
            pair_overlap = int(overlap.loc[left, right])
            left_std = float(stdev.get(left, 0.0))
            right_std = float(stdev.get(right, 0.0))
            reasons: list[str] = []
            if pair_overlap < 2:
                reasons.append("insufficient overlapping observations")
            if left_std == 0.0:
                reasons.append(f"{_measure_axis_label(left)} has zero variance")
            if right_std == 0.0:
                reasons.append(f"{_measure_axis_label(right)} has zero variance")
            if not reasons:
                reasons.append("all pairwise values are missing after aggregation")
            reason_txt = "; ".join(reasons)
            rows.append(
                "<tr>"
                f"<td>{_measure_axis_label(left)}</td>"
                f"<td>{_measure_axis_label(right)}</td>"
                f"<td>{pair_overlap}</td>"
                f"<td>{reason_txt}</td>"
                "</tr>"
            )

    if not rows:
        return (
            "<article><p>No NaN correlation cells detected for the current "
            "2025 dataset.</p></article>"
        )

    total_rows = len(wide)
    body = "".join(rows)
    return f"""
        <article>
            <h2>NaN Diagnostics</h2>
            <p>
                The correlation heatmap is computed from treatment-level seasonal means.
                Input rows after aggregation: <strong>{total_rows}</strong>.
            </p>
            <table>
                <thead>
                    <tr>
                        <th>Measure A</th>
                        <th>Measure B</th>
                        <th>Overlap rows</th>
                        <th>Why NaN</th>
                    </tr>
                </thead>
                <tbody>{body}</tbody>
            </table>
        </article>
    """
