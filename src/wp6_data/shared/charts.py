"""Shared Plotly chart helpers."""

from datetime import date

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def make_line_chart(df: pd.DataFrame, title: str = "Sensor Readings Over Time") -> go.Figure:
    """Create line chart from sensor data.

    Args:
        df: DataFrame with columns: device, sensor, time, value
        title: Chart title

    Returns:
        Plotly Figure object
    """
    df = df.copy()
    df["series"] = df["device"] + " | " + df["sensor"]
    fig = px.line(
        df,
        x="time",
        y="value",
        color="series",
        title=title,
    )
    fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        height=600,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def make_dual_axis_chart(
    df: pd.DataFrame, left: str, right: str, title: str | None = None
) -> go.Figure:
    """Create dual y-axis chart for comparing two sensor types.

    Args:
        df: DataFrame with columns: device, sensor, time, value
        left: Sensor tag for left y-axis
        right: Sensor tag for right y-axis
        title: Optional chart title

    Returns:
        Plotly Figure object
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    left_data = df[df["sensor"] == left]
    right_data = df[df["sensor"] == right]

    for device in left_data["device"].unique():
        d = left_data[left_data["device"] == device]
        fig.add_trace(
            go.Scatter(
                x=d["time"], y=d["value"], name=f"{device} | {left}", mode="lines"
            ),
            secondary_y=False,
        )

    for device in right_data["device"].unique():
        d = right_data[right_data["device"] == device]
        fig.add_trace(
            go.Scatter(
                x=d["time"],
                y=d["value"],
                name=f"{device} | {right}",
                mode="lines",
                line={"dash": "dash"},
            ),
            secondary_y=True,
        )

    chart_title = title or f"{left} vs {right}"
    fig.update_layout(
        template="plotly_white",
        title=chart_title,
        hovermode="x unified",
        height=600,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text=left, secondary_y=False)
    fig.update_yaxes(title_text=right, secondary_y=True)
    return fig


def add_ideal_range(
    fig: go.Figure,
    lo: float | None = None,
    hi: float | None = None,
    mid: float | None = None,
    *,
    y_ref: str = "y",
    x_ref: str = "x",
    orientation: str = "h",
) -> go.Figure:
    """Overlay an ideal-range band and optional centre line on an existing figure.

    Adds Plotly layout shapes in-place:
    - A filled rectangle between *lo* and *hi* (when both are provided).
    - A dashed reference line at *mid* (when provided).

    Args:
        fig: Existing Plotly Figure to modify.
        lo: Lower bound of the ideal range.
        hi: Upper bound of the ideal range.
        mid: Optional centre / target value line.
        y_ref: Y-axis reference (``'y'`` for left axis, ``'y2'`` for right).
        orientation: ``'h'`` for horizontal band (value axis = y) or
            ``'v'`` for vertical band (value axis = x).  Defaults to ``'h'``.

    Returns:
        The same figure with shapes appended.
    """
    shapes = list(fig.layout.shapes or [])

    if lo is not None and hi is not None:
        lo_f, hi_f = float(lo), float(hi)
        if orientation == "h":
            band = dict(
                type="rect",
                xref="paper",
                yref=y_ref,
                x0=0,
                x1=1,
                y0=lo_f,
                y1=hi_f,
                fillcolor="rgba(52, 168, 83, 0.12)",
                line={"width": 0},
                layer="below",
            )
        else:
            band = dict(
                type="rect",
                xref=x_ref,
                yref="paper",
                x0=lo_f,
                x1=hi_f,
                y0=0,
                y1=1,
                fillcolor="rgba(52, 168, 83, 0.12)",
                line={"width": 0},
                layer="below",
            )
        shapes.append(band)

    if mid is not None:
        mid_f = float(mid)
        if orientation == "h":
            line = dict(
                type="line",
                xref="paper",
                yref=y_ref,
                x0=0,
                x1=1,
                y0=mid_f,
                y1=mid_f,
                line={"color": "rgba(52, 168, 83, 0.8)", "width": 1.5, "dash": "dash"},
                layer="above",
            )
        else:
            line = dict(
                type="line",
                xref=x_ref,
                yref="paper",
                x0=mid_f,
                x1=mid_f,
                y0=0,
                y1=1,
                line={"color": "rgba(52, 168, 83, 0.8)", "width": 1.5, "dash": "dash"},
                layer="above",
            )
        shapes.append(line)

    fig.update_layout(shapes=shapes)
    return fig


def make_bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None = None,
    title: str = "",
    y_label: str | None = None,
    barmode: str = "group",
    text_auto: bool = True,
    ideal_lo: float | None = None,
    ideal_hi: float | None = None,
    ideal_mid: float | None = None,
) -> go.Figure:
    """Create a bar chart with optional grouping and ideal range overlay.

    Args:
        df: DataFrame with data to plot
        x: Column name for x-axis
        y: Column name for y-axis values
        color: Optional column name for grouping/coloring bars
        title: Chart title
        y_label: Optional y-axis label (defaults to y column name)
        barmode: Bar mode ('group', 'stack', 'relative')
        text_auto: Show values on bars
        ideal_lo: Lower bound of ideal range band (optional)
        ideal_hi: Upper bound of ideal range band (optional)
        ideal_mid: Centre / target reference line (optional)

    Returns:
        Plotly Figure object
    """
    fig = px.bar(
        df,
        x=x,
        y=y,
        color=color,
        title=title,
        barmode=barmode,
        text_auto=".1f" if text_auto else False,
    )
    fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        height=500,
        yaxis_title=y_label or y,
        xaxis_title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    if text_auto:
        fig.update_traces(textposition="outside")
    if any(v is not None for v in (ideal_lo, ideal_hi, ideal_mid)):
        add_ideal_range(
            fig, ideal_lo, ideal_hi, ideal_mid,
            y_ref="y", orientation="h",
        )

    return fig


def make_heatmap(
    df: pd.DataFrame,
    sensors: list[str] | None = None,
    method: str = "pearson",
    title: str = "Sensor Correlation Matrix",
) -> go.Figure:
    """Create a Pearson (or Spearman/Kendall) correlation heatmap.

    Each sensor series is hourly-resampled and then correlated across the
    overlapping time window.  Sensors with fewer than 2 non-null observations
    after alignment are dropped.

    Args:
        df: DataFrame with columns: device, sensor, time, value.
        sensors: Optional list of ``'device:sensor'`` keys to include.
            When ``None`` all unique ``device+sensor`` combos are used.
        method: Correlation method – ``'pearson'`` (default), ``'spearman'``,
            or ``'kendall'``.
        title: Chart title.

    Returns:
        Plotly Figure with a single heatmap trace.  Returns an empty figure
        with an annotation when fewer than 2 sensors have overlapping data.
    """
    _valid_methods = {"pearson", "spearman", "kendall"}
    if method not in _valid_methods:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Invalid correlation method '{method}'. Choose: pearson, spearman, kendall",
            showarrow=False,
        )
        return fig

    df = df.copy()
    df["key"] = df["device"] + ":" + df["sensor"]

    if sensors is not None:
        df = df[df["key"].isin(sensors)]

    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data available", showarrow=False)
        return fig

    # Pivot to wide format: index=hourly timestamps, columns=device:sensor keys
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["hour"] = df["time"].dt.floor("1h")
    pivot = (
        df.groupby(["hour", "key"])["value"]
        .mean()
        .unstack("key")
        .sort_index()
    )

    # Drop columns with fewer than 2 valid values
    pivot = pivot.dropna(axis=1, thresh=2)

    if pivot.shape[1] < 2:
        fig = go.Figure()
        fig.add_annotation(
            text="Need at least 2 sensors with overlapping data",
            showarrow=False,
        )
        return fig

    corr = pivot.corr(method=method)
    labels = list(corr.columns)
    matrix = corr.values

    # Mask upper triangle (keep diagonal + lower triangle for readability)
    mask = np.triu(np.ones_like(matrix, dtype=bool), k=1)
    display = np.where(mask, np.nan, matrix)

    fig = go.Figure(
        go.Heatmap(
            z=display,
            x=labels,
            y=labels,
            zmin=-1,
            zmax=1,
            colorscale="RdBu",
            reversescale=True,
            colorbar={"title": "r", "thickness": 15},
            hovertemplate=(
                "%{y} × %{x}<br>r = %{z:.3f}<extra></extra>"
            ),
            text=np.where(
                mask,
                "",
                np.vectorize(lambda v: f"{v:.2f}" if not np.isnan(v) else "")(display),
            ),
            texttemplate="%{text}",
            textfont={"size": 11},
        )
    )
    n = len(labels)
    size = max(400, min(900, 80 * n))
    fig.update_layout(
        title=title,
        template="plotly_white",
        height=size,
        width=size,
        xaxis={"side": "bottom", "tickangle": -45},
        yaxis={"autorange": "reversed"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 120, "b": 120, "t": 60, "r": 20},
    )
    return fig


def make_schedule_chart(
    actual_df: pd.DataFrame | None = None,
    predicted_df: pd.DataFrame | None = None,
    natural_df: pd.DataFrame | None = None,
    title: str = "Light Schedule",
    y_label: str = "PAR (μmol/m²/s)",
) -> go.Figure:
    """Create an overlay chart showing actual and predicted PAR.

    Args:
        actual_df: DataFrame with columns: datetime, par (actual PAR readings)
        predicted_df: DataFrame with columns: datetime, par (predicted PAR)
        natural_df: DataFrame with columns: datetime, par (predicted natural light)
        title: Chart title
        y_label: Y-axis label

    Returns:
        Plotly Figure object
    """
    fig = go.Figure()

    # Predicted natural light - filled area (yellow)
    if natural_df is not None and not natural_df.empty:
        fig.add_trace(
            go.Scatter(
                x=natural_df["datetime"],
                y=natural_df["par"],
                name="Natural (predicted)",
                mode="lines",
                fill="tozeroy",
                fillcolor="rgba(251, 188, 4, 0.2)",
                line={"color": "rgb(251, 188, 4)", "width": 1, "dash": "dot"},
            )
        )

    # Predicted PAR - dashed line (orange)
    if predicted_df is not None and not predicted_df.empty:
        fig.add_trace(
            go.Scatter(
                x=predicted_df["datetime"],
                y=predicted_df["par"],
                name="Predicted",
                mode="lines",
                line={"color": "rgb(234, 67, 53)", "width": 2, "dash": "dash"},
            )
        )

    # Actual PAR - filled area (blue)
    if actual_df is not None and not actual_df.empty:
        fig.add_trace(
            go.Scatter(
                x=actual_df["datetime"],
                y=actual_df["par"],
                name="Actual",
                mode="lines",
                fill="tozeroy",
                fillcolor="rgba(66, 133, 244, 0.3)",
                line={"color": "rgb(66, 133, 244)", "width": 2},
            )
        )

    fig.update_layout(
        template="plotly_white",
        title=title,
        hovermode="x unified",
        height=500,
        yaxis_title=y_label,
        xaxis_title="",
        legend={"yanchor": "top", "y": 0.99, "xanchor": "left", "x": 0.01},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def make_stacked_area_chart(
    df: pd.DataFrame,
    x: str,
    y_columns: list[str],
    colors: dict[str, str] | None = None,
    title: str = "",
    y_label: str = "",
) -> go.Figure:
    """Create a stacked area chart.

    Args:
        df: DataFrame with data
        x: Column name for x-axis
        y_columns: List of column names to stack
        colors: Optional dict mapping column names to colors
        title: Chart title
        y_label: Y-axis label

    Returns:
        Plotly Figure object
    """
    fig = go.Figure()

    default_colors = [
        "rgba(66, 133, 244, 0.7)",   # Blue
        "rgba(251, 188, 4, 0.7)",    # Yellow
        "rgba(52, 168, 83, 0.7)",    # Green
        "rgba(234, 67, 53, 0.7)",    # Red
    ]

    for i, col in enumerate(y_columns):
        color = (colors or {}).get(col, default_colors[i % len(default_colors)])
        fig.add_trace(
            go.Scatter(
                x=df[x],
                y=df[col],
                name=col,
                mode="lines",
                fill="tonexty" if i > 0 else "tozeroy",
                fillcolor=color,
                line={"width": 0.5},
                stackgroup="one",
            )
        )

    fig.update_layout(
        template="plotly_white",
        title=title,
        hovermode="x unified",
        height=500,
        yaxis_title=y_label,
        xaxis_title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def build_weekly_coverage(
    records: list[dict],
    project_start: date | None = None,
    project_end: date | None = None,
) -> pd.DataFrame:
    """Bucket daily coverage records into weekly blocks with a status colour.

    Args:
        records: List of dicts with keys: device, sensor, day (date objects).
        project_start: First Monday of the timeline (default: earliest day in records).
        project_end: Last date of the timeline (default: today).

    Returns:
        DataFrame with columns: device, sensor, week_start, days_with_data, status
        Status values: "none" (0 days), "partial" (1-4 days), "good" (5-7 days).
    """
    from datetime import timedelta
    from itertools import groupby

    if project_start is None:
        days = [r["day"] for r in records if r.get("day")]
        project_start = min(days) if days else date.today()
    if project_end is None:
        project_end = date.today()

    # Snap project_start to its Monday
    project_start = project_start - timedelta(days=project_start.weekday())

    # Build list of week-start Mondays
    weeks: list[date] = []
    w = project_start
    while w <= project_end:
        weeks.append(w)
        w += timedelta(weeks=1)

    if not records or not weeks:
        return pd.DataFrame(
            columns=["device", "sensor", "week_start", "days_with_data", "status"]
        )

    # Index: (device, sensor) → set of days
    sorted_records = sorted(records, key=lambda r: (r["device"], r["sensor"]))
    coverage: dict[tuple[str, str], set[date]] = {}
    for key, group in groupby(sorted_records, key=lambda r: (r["device"], r["sensor"])):
        coverage[key] = {r["day"] for r in group}

    rows: list[dict] = []
    for (device, sensor), day_set in sorted(coverage.items()):
        for week_start in weeks:
            week_end = week_start + timedelta(days=6)
            days_in_week = sum(
                1 for d in day_set if week_start <= d <= week_end
            )
            if days_in_week == 7:
                status = "good"
            elif days_in_week >= 3:
                status = "partial"
            else:
                status = "none"
            rows.append({
                "device": device,
                "sensor": sensor,
                "week_start": week_start,
                "days_with_data": days_in_week,
                "status": status,
            })

    return pd.DataFrame(rows)


def render_coverage_grid(weekly_df: pd.DataFrame) -> str:
    """Render an uptime-status-page HTML grid from weekly coverage data.

    Args:
        weekly_df: DataFrame from build_weekly_coverage.

    Returns:
        HTML string with one row per sensor/device, coloured weekly blocks.
    """
    if weekly_df.empty:
        return "<p>No coverage data.</p>"

    color_map = {"good": "#22c55e", "partial": "#eab308", "none": "#ef4444"}
    label_map = {"good": "good", "partial": "some", "none": "no data"}

    weekly_df = weekly_df.copy()

    # Month markers from the weeks
    all_weeks = sorted(weekly_df["week_start"].unique())
    devices = sorted(weekly_df["device"].unique())

    html_parts: list[str] = []
    html_parts.append('<div class="uptime-grid">')

    # Month header row
    html_parts.append('<div class="uptime-row uptime-header">')
    html_parts.append('<div class="uptime-label"></div>')
    html_parts.append('<div class="uptime-blocks">')
    prev_label_idx = -100
    prev_month = None
    for i, w in enumerate(all_weeks):
        month_label = ""
        if prev_month is None or w.month != prev_month:
            # Only show label if enough space since last label (~7 blocks minimum)
            if i - prev_label_idx >= 7:
                month_label = w.strftime("%b %y")
                prev_label_idx = i
            prev_month = w.month
        html_parts.append(
            f'<div class="uptime-month-mark">'
            f'<span>{month_label}</span></div>'
        )
    html_parts.append("</div></div>")

    # Group by device: collapsible, expanded by default
    for device in devices:
        device_df = weekly_df[weekly_df["device"] == device]
        sensors = sorted(device_df["sensor"].unique())
        html_parts.append(
            f'<details open>'
            f'<summary class="uptime-label uptime-device">{device}</summary>'
        )
        for sensor in sensors:
            subset = device_df[device_df["sensor"] == sensor].sort_values("week_start")
            html_parts.append('<div class="uptime-row">')
            html_parts.append(
                f'<div class="uptime-label uptime-sensor">{sensor}</div>'
            )
            html_parts.append('<div class="uptime-blocks">')
            for _, row in subset.iterrows():
                color = color_map[row["status"]]
                status_label = label_map[row["status"]]
                tip = f'{row["week_start"]}: {row["days_with_data"]}/7 days ({status_label})'
                html_parts.append(
                    f'<div class="uptime-block" style="background:{color}" title="{tip}"></div>'
                )
            html_parts.append("</div></div>")
        html_parts.append("</details>")

    html_parts.append("</div>")
    return "\n".join(html_parts)


def prepare_comparison(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    left_label: str,
    right_label: str,
) -> tuple[pd.DataFrame, str, str]:
    """Prepare two DataFrames for a dual-axis comparison chart.

    Relabels the ``sensor`` column in each DataFrame to the given label,
    disambiguating when the labels are identical, then concatenates and
    sorts by time.

    Args:
        left_df: DataFrame (device, sensor, time, value) for the left axis.
        right_df: DataFrame (device, sensor, time, value) for the right axis.
        left_label: Display label for the left series.
        right_label: Display label for the right series.

    Returns:
        Combined DataFrame sorted by time, with ``sensor`` set to the
        (possibly disambiguated) labels.  The caller can pass these labels
        straight into :func:`make_dual_axis_chart`.
    """
    if left_label == right_label:
        left_label += " (left)"
        right_label += " (right)"

    if not left_df.empty:
        left_df = left_df.copy()
        left_df["sensor"] = left_label
    if not right_df.empty:
        right_df = right_df.copy()
        right_df["sensor"] = right_label

    df = pd.concat([left_df, right_df], ignore_index=True)
    if not df.empty:
        df = df.sort_values("time")
    return df, left_label, right_label
