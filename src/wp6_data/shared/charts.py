"""Shared Plotly chart helpers."""


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


def make_bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None = None,
    title: str = "",
    y_label: str | None = None,
    barmode: str = "group",
    text_auto: bool = True,
) -> go.Figure:
    """Create a bar chart with optional grouping.

    Args:
        df: DataFrame with data to plot
        x: Column name for x-axis
        y: Column name for y-axis values
        color: Optional column name for grouping/coloring bars
        title: Chart title
        y_label: Optional y-axis label (defaults to y column name)
        barmode: Bar mode ('group', 'stack', 'relative')
        text_auto: Show values on bars

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
