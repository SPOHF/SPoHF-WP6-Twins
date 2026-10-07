"""Harvest per treatment — per-plant season totals and their build-up per pick.

Both charts come from the ``yield_per_plant`` picks alone: a plant's season
total is the sum of its picks, joined across pick dates by the plant number that
``long_data`` stores as the sample ordinal (see :func:`long_data.plant_nr`).
"""

from html import escape
from typing import Annotated

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.blue.long_data import MEASURE_UNITS, plant_nr
from wp6_data.blue.treatments import (
    TREATMENT_GROUPS,
    TREATMENT_ORDER,
    TREATMENT_PLOTS,
    treatment_color,
    treatment_label,
)
from wp6_data.shared import render_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.charts import CATEGORICAL_COLORS
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter(dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "SPoHF Blue - Harvest per Treatment"
YIELD_SENSOR = "yield_per_plant"
_UNIT = MEASURE_UNITS[YIELD_SENSOR]
_OVERFLOW_COLOR = "#94a3b8"  # pick dates beyond the categorical palette


def prepare_yield(df: pd.DataFrame) -> pd.DataFrame:
    """Raw yield rows → ``treatment, year, pick, plant, value``."""
    out = pd.DataFrame({
        "treatment": df["device"],
        "year": df["time"].dt.year,
        "pick": df["time"].dt.date,
        "plant": df["time"].map(plant_nr),
        "value": df["value"],
    })
    return out[out["treatment"].isin(TREATMENT_ORDER)]


def per_plant_totals(yield_df: pd.DataFrame) -> pd.DataFrame:
    """Season total per plant: ``treatment, plant, total``."""
    return (
        yield_df.groupby(["treatment", "plant"], as_index=False)["value"].sum()
        .rename(columns={"value": "total"})
    )


def pick_means(yield_df: pd.DataFrame) -> pd.DataFrame:
    """Mean yield per plant per pick date over **all** plants of a treatment.

    A plant with no value on a pick date counts as zero, so a treatment's
    pick-date means add up to the mean of its per-plant totals.
    """
    plants = yield_df.groupby("treatment")["plant"].nunique()
    sums = yield_df.groupby(["treatment", "pick"], as_index=False)["value"].sum()
    sums["mean"] = sums["value"] / sums["treatment"].map(plants)
    return sums[["treatment", "pick", "mean"]]


def _present(treatments: pd.Series) -> list[str]:
    seen = set(treatments)
    return [t for t in TREATMENT_ORDER if t in seen]


def _tick(treatment: str, n: int | None = None) -> str:
    """Axis label: code over its field plot (over the plant count)."""
    plot = TREATMENT_PLOTS.get(treatment)
    label = f"{treatment}<br>({plot})" if plot else treatment
    return f"{label}<br>n={n}" if n is not None else label


def _group_dividers(present: list[str]) -> list[dict]:
    """Vertical lines between field groups, in category-index coordinates."""
    shapes: list[dict] = []
    for group in TREATMENT_GROUPS[1:]:
        first = next((i for i, t in enumerate(present) if t in group), None)
        if first:
            shapes.append({
                "type": "line", "xref": "x", "yref": "paper",
                "x0": first - 0.5, "x1": first - 0.5, "y0": 0, "y1": 1,
                "line": {"color": "#d4d4d4", "width": 1},
            })
    return shapes


def _tint(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _layout(fig: go.Figure, title: str, y_title: str, present: list[str]) -> None:
    fig.update_layout(
        template="plotly_white",
        height=460,
        margin={"l": 60, "r": 20, "t": 60, "b": 90},
        title=title,
        yaxis={"title": y_title, "rangemode": "tozero"},
        shapes=_group_dividers(present),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )


def build_totals_chart(totals: pd.DataFrame, year: int) -> go.Figure:
    """Box per treatment of per-plant season totals, every plant as a point."""
    present = _present(totals["treatment"])
    fig = go.Figure()
    ticks: list[str] = []
    for treatment in present:
        tdf = totals[totals["treatment"] == treatment]
        tick = _tick(treatment, len(tdf))
        ticks.append(tick)
        color = treatment_color(treatment)
        fig.add_trace(go.Box(
            x=[tick] * len(tdf),
            y=tdf["total"],
            name=treatment,
            text=[f"Plant {p}" for p in tdf["plant"]],
            boxpoints="all",
            jitter=0.4,
            pointpos=0,
            marker={"color": color, "size": 6, "opacity": 0.6},
            line={"color": color, "width": 2},
            fillcolor=_tint(color, 0.15),
            showlegend=False,
            hovertemplate=(
                f"<b>{treatment_label(treatment)}</b><br>%{{text}}: "
                f"%{{y:.0f}} {_UNIT}<extra></extra>"
            ),
        ))
        mean = tdf["total"].mean()
        fig.add_trace(go.Scatter(
            x=[tick], y=[mean],
            mode="markers",
            marker={"symbol": "diamond", "size": 11, "color": "#111827",
                    "line": {"color": "#ffffff", "width": 2}},
            showlegend=False,
            hovertemplate=(
                f"<b>{treatment_label(treatment)}</b><br>"
                f"Mean: %{{y:.0f}} {_UNIT}<extra></extra>"
            ),
        ))
        fig.add_annotation(
            x=tick, y=tdf["total"].max(), text=f"<b>{mean:.0f}</b>",
            showarrow=False, yshift=12,
        )
    _layout(fig, f"Total harvest per plant per treatment ({year})",
            f"Total yield per plant ({_UNIT})", present)
    fig.update_xaxes(categoryorder="array", categoryarray=ticks)
    return fig


def build_picks_chart(means: pd.DataFrame, year: int) -> go.Figure:
    """Stacked mean yield per plant per pick date, one bar per treatment."""
    present = _present(means["treatment"])
    ticks = [_tick(t) for t in present]
    picks = sorted(means["pick"].unique())
    fig = go.Figure()
    for i, pick in enumerate(picks):
        pdf = means[means["pick"] == pick].set_index("treatment")["mean"]
        label = f"{pick.day} {pick:%b}"
        fig.add_trace(go.Bar(
            x=ticks,
            y=[pdf.get(t) for t in present],
            name=label,
            marker={
                "color": CATEGORICAL_COLORS[i] if i < len(CATEGORICAL_COLORS)
                else _OVERFLOW_COLOR,
                "line": {"color": "#ffffff", "width": 2},
            },
            texttemplate="%{y:.0f}",
            textposition="inside",
            customdata=[treatment_label(t) for t in present],
        hovertemplate=(
            f"<b>%{{customdata}}</b><br>{label}: %{{y:.0f}} {_UNIT}<extra></extra>"
        ),
        ))
    totals = means.groupby("treatment")["mean"].sum()
    for t, tick in zip(present, ticks, strict=True):
        fig.add_annotation(
            x=tick, y=totals[t], text=f"<b>{totals[t]:.0f}</b>",
            showarrow=False, yshift=10,
        )
    _layout(fig, f"Harvest build-up per pick date ({year})",
            f"Mean yield per plant ({_UNIT})", present)
    fig.update_layout(
        barmode="stack",
        bargap=0.35,
        legend={"title": "Pick date", "orientation": "h", "y": -0.25,
                "x": 0.5, "xanchor": "center", "traceorder": "normal"},
        margin={"b": 130},
    )
    return fig


def _summary_table(totals: pd.DataFrame, means: pd.DataFrame) -> str:
    picks = sorted(means["pick"].unique())
    head = "".join(f"<th>{p.day} {p:%b}</th>" for p in picks)
    rows: list[str] = []
    for t in _present(totals["treatment"]):
        tot = totals[totals["treatment"] == t]["total"]
        by_pick = means[means["treatment"] == t].set_index("pick")["mean"]
        cells = "".join(
            f"<td>{by_pick[p]:.0f}</td>" if p in by_pick else "<td>–</td>"
            for p in picks
        )
        rows.append(
            f"<tr><td>{escape(treatment_label(t))}</td><td>{len(tot)}</td>"
            f"<td>{tot.mean():.0f}</td><td>{tot.median():.0f}</td>{cells}</tr>"
        )
    return f"""
        <details>
          <summary>Table view</summary>
          <figure><table>
            <thead><tr><th>Treatment</th><th>Plants</th><th>Mean total</th>
              <th>Median total</th>{head}</tr></thead>
            <tbody>{"".join(rows)}</tbody>
          </table></figure>
          <p><small>Pick-date columns: mean yield per plant ({_UNIT}).</small></p>
        </details>
    """


def _year_selector(years: list[int], selected: int) -> str:
    options = "".join(
        f'<option value="{y}"{" selected" if y == selected else ""}>{y}</option>'
        for y in years
    )
    return f"""
        <form method="get" style="max-width:12rem">
          <label for="year">Year</label>
          <select id="year" name="year" onchange="this.form.submit()">{options}</select>
          <noscript><button type="submit">Show</button></noscript>
        </form>
    """


@router.get("/manual-monitor/harvest", response_class=HTMLResponse)
async def harvest(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    year: Annotated[int | None, Query()] = None,
) -> str:
    """Per-plant season totals and pick-date build-up, for one harvest year."""
    try:
        raw = await provider.fetch_data(
            sensor_tags=[YIELD_SENSOR], device_names=list(TREATMENT_ORDER),
        )
    except Exception as e:
        return _page(f"<p>Error fetching data: {escape(str(e))}</p>")
    if raw.empty:
        return _page("<p>No yield-per-plant data has been uploaded yet.</p>")

    yield_df = prepare_yield(raw)
    years = sorted(yield_df["year"].unique().tolist())
    selected = year if year in years else years[-1]
    year_df = yield_df[yield_df["year"] == selected]
    totals = per_plant_totals(year_df)
    means = pick_means(year_df)

    totals_html = build_totals_chart(totals, selected).to_html(
        full_html=False, include_plotlyjs="cdn",
    )
    picks_html = build_picks_chart(means, selected).to_html(
        full_html=False, include_plotlyjs=False,
    )
    return _page(f"""
        {_year_selector(years, selected)}
        <article>
            <p><small>Box = middle 50%, line = median, ◆ = mean (number above),
            points = individual plants. A plant's total is the sum of its
            picks.</small></p>
            {totals_html}
        </article>
        <article>
            <p><small>Mean per plant per pick date, over all plants of the
            treatment, so the segments add up to the mean total.</small></p>
            {picks_html}
        </article>
        {_summary_table(totals, means)}
    """)


def _page(body: str) -> str:
    return render_page(
        PAGE_TITLE,
        f"<h1>Harvest per Treatment</h1>{body}",
        show_back_link=True,
        back_url="/manual-monitor",
    )
