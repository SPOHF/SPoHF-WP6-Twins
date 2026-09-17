"""The forecast chart: every growth section over time, inside the crop's envelope.

One real time axis, measured on the left and forecast on the right, parted by a
marked "now". The measured half is drawn at close to the sensors' own cadence;
the forecast half only at the horizons the chain was actually fitted and scored
at, so the dashes between those markers are drawn rather than predicted.

**Colour encodes an ordered thing, so it is one hue.** The growth sections are
ordinal (H1 Head → H5 Substrate), which rules out categorical hues: they get a
single-hue ramp running light at the head to dark at the root. Outdoor is
context rather than a section, so it takes neutral ink — which keeps the whole
chart to one hue plus grey.

Adjacent steps of that five-step ramp sit under the ΔE 15 floor for telling two
series apart by colour alone, so identity rests on the other channels as well:
every line is direct-labelled at its end, the lines stack in the same order as
the ramp, and the same numbers appear in the table beneath. Dark steps are
selected for the dark surface, not flipped from the light ones. Alternatives
measured and set aside are in MODEL_PAPER §7.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import plotly.graph_objects as go  # type: ignore[import-untyped]

from wp6_data.red.climate.forecast import ForecastView
from wp6_data.shared.charts import (
    DIVERGING_SCALE,
    SEQUENTIAL_SCALE,
    render_matrix_heatmap_html,
)

# Light at the head to dark at the root: deeper into the canopy, darker. Both
# ramps validated as ordinal — one hue, monotone lightness, ΔL gaps ≥ 0.06,
# light end ≥ 2:1 on its own surface. Adjacent steps sit at ~9.7 ΔE and the
# lightness range is boxed in at both ends, so widening does not help; see the
# module docstring for what carries identity instead.
SECTION_RAMP_LIGHT = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")
SECTION_RAMP_DARK = ("#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4")

# Outdoor is context, not a section, so it takes neutral ink rather than a step
# on the ramp — which also keeps the chart to a single hue plus grey.
OUTDOOR_LIGHT = "#52514e"
OUTDOOR_DARK = "#c3c2b7"

# The envelope is a region, not a series, so it is neutral rather than a sixth
# step on the ramp.
#
# The alphas are measured, not guessed. At the original 0.10 the light fill sat
# at 1.16 contrast against the page — indistinguishable from it. These sit at
# 1.41 and 1.45, matched across modes so a value tuned on one does not read as
# heavy on the other, and chosen as the strongest tint that still leaves the
# section lines legible over it: the middle ramp steps keep 2.1-4.6 contrast
# against the band, and only the lightest step drops to 1.46 — and that is the
# line drawn along the band's own edge, half of it over the surface.
BAND_FILL_LIGHT = "rgba(82, 81, 78, 0.22)"
BAND_FILL_DARK = "rgba(195, 194, 183, 0.17)"

# Surface colours, used for the ring that keeps overlapping markers legible.
SURFACE_LIGHT = "#fcfcfb"
SURFACE_DARK = "#1a1a19"

LINE_WIDTH = 2
MARKER_SIZE = 9
MARKER_RING = 2


def section_colour(height: int, ramp: tuple[str, ...] = SECTION_RAMP_LIGHT) -> str:
    """The ramp step for a growth section, keyed by its height.

    Keyed by **height, not by position in the list of sections present**: a wire
    that has lost H4 must not repaint H5 with H4's colour. Colour follows the
    section, never its rank among whichever sections happen to be reporting.
    """
    return ramp[(height - 1) % len(ramp)]


def typical_uncertainty(view: ForecastView) -> list[tuple[str, float]]:
    """The ± at each horizon, which barely varies between sections.

    Combined error is ``√(link2² + link3²)`` and link 2 dominates, so at a given
    horizon every section carries almost the same spread — on real data, ±3.49
    to ±3.53 across all five at +6 h. That makes uncertainty a property of the
    *horizon*, which is why it is stated once per horizon rather than drawn as
    five nearly identical error bars over five lines.
    """
    rows = []
    for snapshot in view.snapshots:
        spreads = [p.uncertainty for p in snapshot.points if p.uncertainty is not None]
        if spreads:
            rows.append((snapshot.label, round(sum(spreads) / len(spreads), 1)))
    return rows


def _local(moment, tz) -> datetime:
    """UTC instant as a naive local datetime.

    Plotly renders timestamps in UTC, so a naive local value is what makes the
    axis read in the dashboard's display timezone. Same trick as
    ``shared.time.to_local_isoformat``, done server-side so the conversion is
    not split across server and client.
    """
    return moment.astimezone(tz).replace(tzinfo=None)


def _section_traces(view: ForecastView, height: int, tz):
    """Measured (dense) and forecast (sparse) halves of one section's line."""
    measured = [
        (_local(moment, tz), value)
        for moment, value in view.measured_trace.get(height, [])
    ]
    forecast = [
        (_local(snapshot.at, tz), point.value)
        for snapshot in view.snapshots
        if snapshot.is_now or not snapshot.measured
        for point in snapshot.points
        if point.height == height
    ]
    return measured, sorted(forecast)


def forecast_band_chart(view: ForecastView, timezone: str) -> str | None:
    """Every growth section over time, inside the crop's envelope.

    The measured half is drawn at close to the sensors' own cadence and the
    forecast half at the horizons the chain was actually fitted for, on **one
    real time axis**. So the left of the chart is a dense record and the right
    is a handful of predicted points fanning out from it — which is honest about
    which half is observation and which is inference, without the axis having to
    pretend the horizons are evenly spaced.

    Uncertainty is not drawn here. It is stated per horizon beneath the chart,
    carried per point in the hover, and given per section in the table; five
    overlapping error ranges would obscure the gradient this chart exists to
    show.

    Returns ``None`` when there is nothing to draw.
    """
    tz = ZoneInfo(timezone)
    heights = view.heights
    if not heights:
        return None

    # The envelope spans whatever sections reported at each instant, so a wire
    # that has lost a height reads as a missing section rather than a narrower
    # crop.
    spread: dict[datetime, list[float]] = {}
    for height in heights:
        measured, forecast = _section_traces(view, height, tz)
        for moment, value in [*measured, *forecast]:
            spread.setdefault(moment, []).append(value)
    band = sorted((m, min(v), max(v)) for m, v in spread.items() if v)
    if not band:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[m for m, _, _ in band], y=[hi for _, _, hi in band],
            mode="lines", line=dict(width=0), hoverinfo="skip",
            showlegend=False, name="",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[m for m, _, _ in band], y=[lo for _, lo, _ in band],
            mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor=BAND_FILL_LIGHT, hoverinfo="skip",
            name="Spread across sections",
        )
    )

    for height in heights:
        measured, forecast = _section_traces(view, height, tz)
        colour = section_colour(height, SECTION_RAMP_LIGHT)
        label = f"H{height} {view.label_for(height)}"
        group = f"section-{height}"

        if measured:
            fig.add_trace(
                go.Scatter(
                    x=[m for m, _ in measured], y=[v for _, v in measured],
                    mode="lines", name=label, legendgroup=group, showlegend=True,
                    line=dict(color=colour, width=LINE_WIDTH),
                    hovertemplate=(
                        f"{label}<br>%{{y:.1f}} {view.unit}"
                        "<br>%{x|%a %H:%M}<extra></extra>"
                    ),
                )
            )
        if len(forecast) > 1:
            # Markers only on the forecast: each one is a horizon the chain was
            # fitted and scored at, and the dashes between them are drawn, not
            # predicted.
            fig.add_trace(
                go.Scatter(
                    x=[m for m, _ in forecast], y=[v for _, v in forecast],
                    mode="lines+markers", name=label, legendgroup=group,
                    showlegend=not measured,
                    line=dict(color=colour, width=LINE_WIDTH, dash="dash"),
                    marker=dict(
                        color=colour, size=MARKER_SIZE,
                        line=dict(color=SURFACE_LIGHT, width=MARKER_RING),
                    ),
                    hovertemplate=(
                        f"{label}<br>%{{y:.1f}} {view.unit}"
                        "<br>%{x|%a %H:%M}<extra></extra>"
                    ),
                )
            )
        end = forecast[-1] if forecast else (measured[-1] if measured else None)
        if end is not None:
            _label_line(fig, end[0], end[1], label, colour)

    if view.outdoor_trace or view.outdoor:
        measured = [(_local(m, tz), v) for m, v in view.outdoor_trace]
        forecast = sorted(
            (_local(snapshot.at, tz), point.value)
            for point in view.outdoor if not point.measured
            for snapshot in view.snapshots
            if not snapshot.measured and snapshot.label == point.label
        )
        # Start the dashed half at the last measured point, so the outdoor line
        # is continuous across "now". The sections get this for free — their
        # forecast half includes the hinge snapshot — but outdoor is keyed on
        # snapshots that are *not* measured, which excludes the hinge.
        if measured and forecast:
            forecast.insert(0, measured[-1])
        for part, dash, show in ((measured, "solid", True), (forecast, "dash", False)):
            if len(part) < 2:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[m for m, _ in part], y=[v for _, v in part],
                    mode="lines", name="Outdoor", legendgroup="outdoor",
                    showlegend=show,
                    line=dict(color=OUTDOOR_LIGHT, width=LINE_WIDTH, dash=dash),
                    hovertemplate=(
                        f"Outdoor<br>%{{y:.1f}} {view.unit}"
                        "<br>%{x|%a %H:%M}<extra></extra>"
                    ),
                )
            )
        tail = forecast[-1] if forecast else (measured[-1] if measured else None)
        if tail is not None:
            _label_line(fig, tail[0], tail[1], "Outdoor", OUTDOOR_LIGHT)

    if view.now is not None:
        # Shape plus annotation rather than `add_vline(annotation_text=...)`:
        # that helper averages its x positions to place the label, which throws
        # on a date axis — and it attaches an annotation of its own, which is
        # what once silently displaced H1's label.
        hinge = _local(view.now.at, tz)
        fig.add_shape(
            type="line", x0=hinge, x1=hinge, xref="x", yref="paper", y0=0, y1=1,
            line=dict(color="rgba(82,81,78,0.45)", width=1, dash="dot"),
        )
        fig.add_annotation(
            x=hinge, y=1, xref="x", yref="paper", text="forecast →",
            showarrow=False, xanchor="left", yanchor="bottom", xshift=4,
            font=dict(size=11, color=OUTDOOR_LIGHT),
        )

    fig.update_layout(
        template="plotly_white",
        height=380,
        margin=dict(l=10, r=120, t=30, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(title="", type="date"),
        yaxis=dict(title=view.quantity, zeroline=False),
    )
    return fig.to_html(
        full_html=False, include_plotlyjs="cdn",
        config={"responsive": True, "displaylogo": False},
    ) + _band_theme_script()


def _label_line(fig, x, y, text: str, colour: str) -> None:
    """Attach a direct label to the end of a line."""
    fig.add_annotation(
        x=x, y=y, text=text, showarrow=False,
        xanchor="left", yanchor="middle", xshift=8,
        font=dict(size=11, color=colour),
    )


def _band_theme_script() -> str:
    """Select the dark hues for a dark surface, rather than flipping the light ones."""
    light = list(SECTION_RAMP_LIGHT)
    dark = list(SECTION_RAMP_DARK)
    return f"""
<script>
(function () {{
  var light = {light!r}.map(String), dark = {dark!r}.map(String);
  function apply() {{
    var isDark = document.documentElement.dataset.theme === 'dark';
    var colours = isDark ? dark : light;
    document.querySelectorAll('.js-plotly-plot').forEach(function (plot) {{
      var band = (plot.data || []).findIndex(function (t) {{ return t.fill === 'tonexty'; }});
      if (band < 0) return;
      window.Plotly.restyle(plot, {{fillcolor:
        isDark ? {BAND_FILL_DARK!r} : {BAND_FILL_LIGHT!r}}}, [band]);
      // Two traces per section (measured, forecast) follow the fill.
      (plot.data || []).forEach(function (trace, index) {{
        if (index <= band) return;
        var group = trace.legendgroup || '';
        var colour;
        if (group === 'outdoor') {{
          colour = isDark ? {OUTDOOR_DARK!r} : {OUTDOOR_LIGHT!r};
        }} else {{
          var slot = parseInt(group.replace('section-', ''), 10);
          colour = colours[(slot - 1) % colours.length];
        }}
        if (!colour) return;
        window.Plotly.restyle(plot, {{
          'line.color': colour, 'marker.color': colour,
          'marker.line.color': isDark ? {SURFACE_DARK!r} : {SURFACE_LIGHT!r},
        }}, [index]);
      }});
      // Matched by label text, not by index: the forecast divider adds an
      // annotation of its own, so indices do not line up with the series.
      var byText = {{}};
      (plot.data || []).forEach(function (trace) {{
        var group = trace.legendgroup || '';
        if (!group || !trace.name) return;
        byText[trace.name] = group === 'outdoor'
          ? (isDark ? {OUTDOOR_DARK!r} : {OUTDOOR_LIGHT!r})
          : colours[(parseInt(group.replace('section-', ''), 10) - 1) % colours.length];
      }});
      var notes = (plot.layout.annotations || []).map(function (a) {{
        var colour = byText[a.text];
        return colour
          ? Object.assign({{}}, a, {{font: Object.assign({{}}, a.font, {{color: colour}})}})
          : a;
      }});
      if (notes.length) window.Plotly.relayout(plot, {{annotations: notes}});
    }});
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', apply);
  }} else {{ apply(); }}
}})();
</script>
"""


# ── model-page matrices ────────────────────────────────────────────────────
#
# Skill has a meaningful zero — beat the baseline or didn't — so it takes the
# diverging scale with grey at nought: a cell that earned nothing shows as no
# colour, and a loss shows as the opposite of a gain. RMSE has no crossing
# point, only magnitude, so it takes the sequential one.

# Smallest half-range a skill matrix is drawn over. Without a floor, a run where
# everything scored ±0.03 would paint itself in strong colour and read as a
# triumph; with one, a weak matrix looks weak.
MIN_SKILL_BOUND = 0.3


def diverging_bound(values: list[float | None], floor: float = MIN_SKILL_BOUND) -> float:
    """Symmetric half-range for a diverging scale, so grey always lands on zero."""
    peak = max((abs(v) for v in values if v is not None), default=0.0)
    return max(floor, math.ceil(peak * 10) / 10)


def skill_matrix_chart(
    z: list[list[float | None]],
    x_labels: list[str],
    y_labels: list[str],
    *,
    baseline: str,
    include_js: bool = True,
    x_title: str = "",
) -> str | None:
    """Skill against one baseline, as a diverging matrix.

    Read the colour, not the number: blue beat the baseline, red lost to it,
    grey did neither. The numbers are printed in the cells as well, so the
    matrix is also the table.
    """
    if not z or not y_labels:
        return None
    bound = diverging_bound([value for row in z for value in row])
    return render_matrix_heatmap_html(
        z, x_labels, y_labels,
        colorscale=DIVERGING_SCALE, zmin=-bound, zmax=bound,
        value_label=f"skill vs {baseline}", include_js=include_js,
        x_title=x_title,
    )


MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def period_error_chart(
    rows: list[tuple[int, list[tuple[int, float]]]],
    unit: str,
    *,
    tick: Callable[[int], str],
    x_title: str,
    include_js: bool = True,
) -> str | None:
    """Held-out error across a repeating period, one row per horizon.

    Used twice, for the two ways a single RMSE misleads: error concentrated in
    part of the *day*, and error concentrated in part of the *year*. Both are
    invisible in the headline figure and both change what it means.

    ``rows`` is ``(horizon_hours, [(key, rmse), ...])``.
    """
    populated = [(horizon, table) for horizon, table in rows if table]
    if not populated:
        return None

    keys = sorted({key for _, table in populated for key, _ in table})
    z = [[dict(table).get(key) for key in keys] for _, table in populated]
    return render_matrix_heatmap_html(
        z,
        [tick(key) for key in keys],
        [f"+{horizon} h" for horizon, _ in populated],
        colorscale=SEQUENTIAL_SCALE,
        value_label=f"RMSE ({unit})" if unit else "RMSE",
        value_format=".2f", include_js=include_js, x_title=x_title,
    )


def month_error_chart(
    rows: list[tuple[int, list[tuple[int, float]]]], unit: str,
    *, include_js: bool = True,
) -> str | None:
    """Error by calendar month — does the model hold up across the seasons?"""
    return period_error_chart(
        rows, unit, tick=lambda m: MONTH_NAMES[m - 1],
        x_title="month", include_js=include_js,
    )


def hour_error_chart(
    rows: list[tuple[int, list[tuple[int, float]]]],
    unit: str,
    *,
    include_js: bool = True,
) -> str | None:
    """Held-out error by hour of day, one row per horizon.

    The diagnostic that separates a model which learnt the day's *shape* from
    one that merely tracks its daily mean — both score the same overall, and
    only this tells them apart. Error concentrated in the middle of the day
    means the diurnal swing is where the model is losing.

    ``rows`` is ``(horizon_hours, [(hour, rmse), ...])``.
    """
    return period_error_chart(
        rows, unit, tick=lambda h: f"{h:02d}",
        x_title="hour of day", include_js=include_js,
    )
