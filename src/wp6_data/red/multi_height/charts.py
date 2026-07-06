"""Plotly figure builders for the red multi-height views."""

import pandas as pd  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]

from ..db import WIRE_SENSOR_HEIGHTS, WIRE_SENSOR_MEASUREMENTS, wire_device_id
from ..risk.metrics import compute_cumulative_dli, vpd_series, wet_hours_series
from ..utils import (
    PAR_COLORSCALE,
    svg_rect_to_plotly_rect,
    svg_to_data_uri,
    value_to_color,
)
from .cells import (
    CO2_FLOOR_COLOR,
    FUNGAL_COLOR,
    HEIGHT_DLI_COLOR,
    MEASUREMENT_COLORS,
    RISK_LABELS,
    VPD_LINE_COLOR,
    WIRE_MEASUREMENT_LABELS,
    fmt_local,
    format_reading,
)
from .svg import SVG_BACKGROUND_PATH

### Wire Sensor Trends ###
# One trace colour per height, shared across all four charts so a given height
# reads as the same colour everywhere. Five colours for the five heights.
WIRE_HEIGHT_COLORS = ["#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#10b981"]


def make_wire_measurement_plot(df, measurement, timezone):
    """Line chart for one measurement type, one line per height."""
    label, unit = WIRE_MEASUREMENT_LABELS[measurement]
    data = df[df["measurement"] == measurement] if not df.empty else df

    fig = go.Figure()

    for height in WIRE_SENSOR_HEIGHTS:
        d = data[data["height"] == height].sort_values("time") if not data.empty else data

        if d.empty:
            continue

        color = WIRE_HEIGHT_COLORS[(height - 1) % len(WIRE_HEIGHT_COLORS)]

        fig.add_trace(
            go.Scatter(
                # Convert UTC → local wall-clock so the axis matches the picker
                x=d["time"].dt.tz_convert(timezone).dt.tz_localize(None),
                y=d["value"],
                name=f"Height {height}",
                mode="lines",
                connectgaps=False,
                line=dict(color=color, width=2),
                hovertemplate=(
                    f"<b>Height {height}</b><br>%{{x|%Y-%m-%d %H:%M}}<br>"
                    f"{label}: %{{y:.2f}} {unit}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        height=360,
        hovermode="x unified",
        xaxis_title="Time",
        yaxis_title=f"{label} ({unit})",
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


# Lane colour per risk — reuse each metric's own hue so the timeline matches the
# detail charts and column accents (CO₂ uses the floor-marker red).
RISK_COLORS = {
    "vpd": VPD_LINE_COLOR,
    "fungal": FUNGAL_COLOR,
    "co2": CO2_FLOOR_COLOR,
    "canopy": HEIGHT_DLI_COLOR,
}
# Within a section, lanes read top-down in this order (matches the table columns).
RISK_LANE_ORDER = {"canopy": 0, "vpd": 1, "fungal": 2, "co2": 3}
# Compact tick label per lane — the section is carried by the band, not repeated.
RISK_SHORT = {"vpd": "VPD", "fungal": "Fungal", "co2": "CO₂", "canopy": "Canopy"}
# Extra y-spacing between height blocks (lanes within a block step by 1.0), so a
# section's risks hug together while sections stay visually apart.
GANTT_GROUP_GAP = 0.7


def risk_gantt(episodes, timezone: str, day_start) -> str | None:
    """Gantt-style timeline of one day's risk episodes (inline Plotly HTML).

    One lane per ``(section, risk)`` that actually fired that day — empty lanes
    are omitted, so a calm day stays short and parallel risks never collide
    (each risk owns its own lane). Every episode is a thick horizontal bar from
    start to end; a span that began before midnight or is still ongoing is
    *clamped* to the day window for drawing, while the hover keeps its true
    times. Returns ``None`` when there are no episodes (caller shows a note).

    ``day_start`` is the tz-aware local midnight of the shown day.
    """
    if not episodes:
        return None

    day0 = day_start.tz_localize(None)  # naive local midnight (Plotly x-axis space)
    day1 = day0 + pd.Timedelta(days=1)

    def _local(dt):
        return pd.Timestamp(dt).tz_convert(timezone).tz_localize(None)

    lanes: dict[tuple, list] = {}
    for e in episodes:
        lanes.setdefault((e["height"], e["label"], e["risk"]), []).append(e)
    # Top-down: by height, then the fixed risk order within a section.
    keys = sorted(lanes, key=lambda k: (k[0], RISK_LANE_ORDER.get(k[2], 9)))

    # Lanes sit at explicit y-positions (linear axis), not evenly-spaced
    # categories: a 1.0 step within a section, a wider GANTT_GROUP_GAP between
    # sections — so a section's lanes (e.g. H1's Canopy + VPD) hug together while
    # the sections stay clearly apart.
    pos, prev_h = [], None
    y = 0.0
    for height, _label, _risk in keys:
        if prev_h is None:
            y = 0.0
        elif height != prev_h:
            y += 1.0 + GANTT_GROUP_GAP
        else:
            y += 1.0
        pos.append(y)
        prev_h = height

    fig = go.Figure()
    legended: set[str] = set()
    for idx, (height, label, risk) in enumerate(keys):
        cat = f"H{height} {label} · {RISK_LABELS[risk]}"
        color = RISK_COLORS.get(risk, "#6b7280")
        for e in lanes[(height, label, risk)]:
            start = max(_local(e["start_time"]), day0)
            ongoing = e["end_time"] is None
            end = day1 if ongoing else min(_local(e["end_time"]), day1)
            ends = "ongoing" if ongoing else fmt_local(e["end_time"], timezone)
            fig.add_trace(go.Scatter(
                x=[start, end], y=[pos[idx], pos[idx]], mode="lines",
                line=dict(color=color, width=18),
                legendgroup=risk, name=RISK_LABELS[risk],
                showlegend=risk not in legended,
                hovertemplate=(
                    f"<b>{cat}</b><br>"
                    f"{fmt_local(e['start_time'], timezone)} → {ends}"
                    f"<br>peak {e['peak']:.2f}<extra></extra>"
                ),
            ))
            legended.add(risk)

    # Group lanes into per-height blocks: an alternating band, a separator line
    # between blocks, and one section label per block — so the heights read as
    # distinct groups instead of a flat stack of look-alike lanes.
    shapes, annotations = [], []
    i, band = 0, 0
    while i < len(keys):
        h, label, _ = keys[i]
        j = i
        while j < len(keys) and keys[j][0] == h:
            j += 1
        top, bot = pos[i] - 0.5, pos[j - 1] + 0.5
        if band % 2 == 1:  # shade every other block
            shapes.append(dict(
                type="rect", xref="paper", x0=0, x1=1, yref="y",
                y0=top, y1=bot, layer="below", line_width=0,
                fillcolor="rgba(99,102,241,0.06)",
            ))
        if i > 0:  # rule midway between this block and the one above
            edge = (pos[i - 1] + pos[i]) / 2
            shapes.append(dict(
                type="line", xref="paper", x0=0, x1=1, yref="y",
                y0=edge, y1=edge, line=dict(color="#d1d5db", width=1),
            ))
        annotations.append(dict(
            xref="paper", x=0, xanchor="right", xshift=-54,
            yref="y", y=(pos[i] + pos[j - 1]) / 2, text=f"<b>H{h}</b> {label}",
            showarrow=False, font=dict(size=11, color="#374151"),
        ))
        i, band = j, band + 1

    span = (pos[-1] - pos[0]) if pos else 0.0
    fig.update_layout(
        template="plotly_white",
        height=int(26 * span + 80),
        margin=dict(l=150, r=20, t=8, b=36),
        xaxis=dict(range=[day0, day1], title="Time of day",
                   tickformat="%H:%M", dtick=3 * 3600 * 1000),
        yaxis=dict(tickmode="array", tickvals=pos,
                   ticktext=[RISK_SHORT.get(k[2], k[2]) for k in keys],
                   range=[pos[-1] + 0.6, pos[0] - 0.6]),  # high→low = top-down
        shapes=shapes, annotations=annotations,
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig.to_html(
        full_html=False, include_plotlyjs="cdn",
        config={"responsive": True, "displaylogo": False},
    )


def detail_chart(hdf, metric, timezone, risk_t, day_start):
    """Full line chart for one height + metric over the day (row expansion).

    ``hdf`` may include a pre-day look-back; every metric is scoped to the shown
    day except fungal wet-hours, which integrate the look-back and then trim.
    """
    fig = go.Figure()
    title, ytitle = metric, ""

    def _local(s):
        return s.dt.tz_convert(timezone).dt.tz_localize(None)

    day_df = hdf[hdf["time"] >= day_start] if not hdf.empty else hdf
    if metric in WIRE_SENSOR_MEASUREMENTS:
        label, unit = WIRE_MEASUREMENT_LABELS[metric]
        d = day_df[day_df["measurement"] == metric].sort_values("time")
        if not d.empty:
            fig.add_trace(go.Scatter(
                x=_local(d["time"]), y=d["value"], mode="lines",
                line=dict(color=MEASUREMENT_COLORS[metric], width=2), name=label,
            ))
        if metric == "co2":  # mark the carbon-limitation floor (see sparkline)
            fig.add_hline(y=risk_t.co2.floor_ppm, line_dash="dot",
                          line_color=CO2_FLOOR_COLOR, annotation_text="floor")
        title, ytitle = label, f"{label} ({unit})"
    elif metric == "dli":
        cum = compute_cumulative_dli(day_df[day_df["measurement"] == "par"][["time", "value"]])
        if cum is not None and not cum.empty:
            fig.add_trace(go.Scatter(
                x=_local(cum["time"]), y=cum["cumulative_dli"], mode="lines",
                line=dict(color=HEIGHT_DLI_COLOR, width=2), name="Height DLI",
            ))
        fig.add_hline(y=risk_t.canopy_dli.target_mol, line_dash="dot",
                      line_color=HEIGHT_DLI_COLOR, annotation_text="target")
        title, ytitle = "Cumulative Height DLI", "mol/m²"
    elif metric == "vpd":
        v = vpd_series(day_df)
        if not v.empty:
            fig.add_trace(go.Scatter(
                x=_local(v["time"]), y=v["value"], mode="lines",
                line=dict(color=VPD_LINE_COLOR, width=2), name="VPD",
            ))
        fig.add_hrect(y0=risk_t.vpd.band_min_kpa, y1=risk_t.vpd.band_max_kpa,
                      fillcolor="#16a34a", opacity=0.12, line_width=0)
        title, ytitle = "VPD vs healthy band", "kPa"
    elif metric == "fungal":
        w = wet_hours_series(
            hdf[hdf["measurement"] == "hum"][["time", "value"]],
            risk_t.fungal.rh_pct, risk_t.fungal.window_hours,
        )
        if not w.empty:
            w = w[w["time"] >= day_start]
        if not w.empty:
            fig.add_trace(go.Scatter(
                x=_local(w["time"]), y=w["value"], mode="lines",
                line=dict(color=FUNGAL_COLOR, width=2), name="Wet-hours",
            ))
        fig.add_hline(y=risk_t.fungal.active_wet_hours, line_dash="dot",
                      line_color=FUNGAL_COLOR, annotation_text="active")
        title, ytitle = "Fungal risk (wet-hours)", "hours"

    fig.update_layout(
        template="plotly_white", height=380, title=title,
        xaxis_title="Time of day", yaxis_title=ytitle, hovermode="x unified",
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


### Plot ###
def make_mh_greenhouse_plot(
    metrics,
    canvas_w,
    canvas_h,
    sensor_boxes,
    sensor_bands,
    target_day,
    value_label="PAR",
    show_bands=True,
):
    fig = go.Figure()

    # fix background
    fig.add_shape(
        type="rect",
        x0=0,
        x1=canvas_w,
        y0=0,
        y1=canvas_h,
        fillcolor="#ffffff",
        line=dict(width=0),
        layer="below",
    )

    latest_vals = metrics["latest_value"].dropna()
    dli_vals = metrics["dli_today"].dropna()

    latest_min = float(latest_vals.min()) if not latest_vals.empty else 0.0
    latest_max = float(latest_vals.max()) if not latest_vals.empty else 1.0

    dli_min = float(dli_vals.min()) if not dli_vals.empty else 0.0
    dli_max = float(dli_vals.max()) if not dli_vals.empty else 1.0

    # background
    fig.add_layout_image(
        dict(
            source=svg_to_data_uri(SVG_BACKGROUND_PATH),
            xref="x",
            yref="y",
            x=0,
            y=canvas_h,
            sizex=canvas_w,
            sizey=canvas_h,
            sizing="stretch", #bg fix
            layer="below",
        )
    )

    for _, row in metrics.iterrows():
        sid = row["sensor_id"]

        # --- bands (DLI shading; PAR only) ---
        if show_bands and sid in sensor_bands:
            x0, x1, y0, y1 = svg_rect_to_plotly_rect(sensor_bands[sid], canvas_h)

            fig.add_shape(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=value_to_color(row["dli_today"], dli_min, dli_max, alpha=0.4),
                line=dict(width=0),
                layer="below",
            )

        # --- sensor box ---
        if sid in sensor_boxes:
            x0, x1, y0, y1 = svg_rect_to_plotly_rect(sensor_boxes[sid], canvas_h)

            fig.add_shape(
                type="rect",
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
                fillcolor=value_to_color(
                    row["latest_value"], latest_min, latest_max, alpha=0.9,
                ),
                line=dict(color="#111111", width=1.5),
            )

            label = (
                "—" if pd.isna(row["latest_value"])
                else format_reading(row["latest_value"])
            )

            fig.add_annotation(
                x=(x0 + x1) / 2,
                y=(y0 + y1) / 2,
                text=label,
                showarrow=False,
                font=dict(size=11, color="#111111"),
                xanchor="center",
                yanchor="middle",
            )

    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(
                color=[latest_min, latest_max],
                colorscale=PAR_COLORSCALE,
                cmin=latest_min,
                cmax=latest_max,
                showscale=True,
                colorbar=dict(
                    title=dict(
                        text=value_label,
                        font=dict(color="#111111"),
                    ),
                    tickfont=dict(color="#111111"),
                    bgcolor="white",
                )
            ),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"{target_day.date()}",
            font=dict(color="#111111"),
        ),

        width=850,
        height=760,

        margin=dict(l=20, r=20, t=60, b=20),

        plot_bgcolor="white",
        paper_bgcolor="white",

        font=dict(
            color="#111111",
        ),

        hoverlabel=dict(
            bgcolor="white",
            font_color="#111111",
        )
    )

    fig.update_xaxes(range=[0, canvas_w], visible=False)
    fig.update_yaxes(range=[0, canvas_h], visible=False)

    return fig


### Cumulative DLI line chart ###
DLI_LINE_COLORS = [
    "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#10b981",
]


def make_cumulative_dli_plot(df_day, timezone, target_day, wire):
    """Line chart of cumulative DLI through the day, one line per height (one wire)."""
    fig = go.Figure()

    for i, height in enumerate(WIRE_SENSOR_HEIGHTS):
        device = wire_device_id(wire, height)
        cum = compute_cumulative_dli(df_day[df_day["device"] == device])

        if cum is None or cum.empty:
            continue

        label = f"H{height}"
        color = DLI_LINE_COLORS[i % len(DLI_LINE_COLORS)]

        fig.add_trace(
            go.Scatter(
                # Convert UTC → local wall-clock so the axis matches the day shown
                x=cum["time"].dt.tz_convert(timezone).dt.tz_localize(None),
                y=cum["cumulative_dli"],
                name=label,
                mode="lines",
                line=dict(color=color, width=2),
                hovertemplate=(
                    f"<b>{label}</b><br>%{{x|%H:%M}}<br>"
                    "DLI: %{y:.2f} mol/m²<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        title=dict(text=f"Cumulative DLI — {target_day.date()}"),
        height=420,
        hovermode="x unified",
        xaxis_title="Time of day",
        yaxis_title="Cumulative DLI (mol/m²)",
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig
