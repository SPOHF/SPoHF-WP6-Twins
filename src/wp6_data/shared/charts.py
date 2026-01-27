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
    fig.update_layout(hovermode="x unified", height=600)
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
    fig.update_layout(title=chart_title, hovermode="x unified", height=600)
    fig.update_yaxes(title_text=left, secondary_y=False)
    fig.update_yaxes(title_text=right, secondary_y=True)
    return fig
