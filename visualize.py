#!/usr/bin/env python3
"""Interactive time-series visualization of sensor data."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg
from plotly.subplots import make_subplots
from psycopg.rows import dict_row

# TimescaleDB connection
DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"


def fetch_sensor_data(sensor_tags: list[str] | None = None, limit: int = 10000) -> pd.DataFrame:
    """Fetch sensor readings from TimescaleDB."""
    conditions = []
    params: dict = {"limit": limit}
    if sensor_tags:
        conditions.append("sensor_tag = ANY(%(tags)s)")
        params["tags"] = sensor_tags

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT device_name AS device, sensor_tag AS sensor,
               time, value
        FROM readings
        {where}
        ORDER BY time
        LIMIT %(limit)s
    """

    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        records = cur.fetchall()

    df = pd.DataFrame(records)
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.sort_values("time")
    return df


def plot_time_series(df: pd.DataFrame, title: str = "Sensor Readings Over Time"):
    """Create interactive plotly chart."""
    if df.empty:
        print("No data to plot")
        return

    # Create a combined label for color grouping
    df["series"] = df["device"] + " | " + df["sensor"]

    fig = px.line(
        df,
        x="time",
        y="value",
        color="series",
        title=title,
        labels={"time": "Time", "value": "Value", "series": "Device | Sensor"},
    )

    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Value",
        legend_title="Sensor",
        hovermode="x unified",
    )

    fig.show()


def plot_dual_axis(df: pd.DataFrame, left_sensor: str, right_sensor: str):
    """Create dual y-axis chart for comparing two sensor types."""
    if df.empty:
        print("No data to plot")
        return

    left_data = df[df["sensor"] == left_sensor].copy()
    right_data = df[df["sensor"] == right_sensor].copy()

    if left_data.empty:
        print(f"No data for {left_sensor}")
        return
    if right_data.empty:
        print(f"No data for {right_sensor}")
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Group by device for left axis
    for device in left_data["device"].unique():
        device_data = left_data[left_data["device"] == device]
        fig.add_trace(
            go.Scatter(
                x=device_data["time"],
                y=device_data["value"],
                name=f"{device} | {left_sensor}",
                mode="lines",
            ),
            secondary_y=False,
        )

    # Group by device for right axis
    for device in right_data["device"].unique():
        device_data = right_data[right_data["device"] == device]
        fig.add_trace(
            go.Scatter(
                x=device_data["time"],
                y=device_data["value"],
                name=f"{device} | {right_sensor}",
                mode="lines",
                line=dict(dash="dash"),
            ),
            secondary_y=True,
        )

    fig.update_layout(
        title=f"{left_sensor} vs {right_sensor}",
        hovermode="x unified",
    )
    fig.update_xaxes(title_text="Time")
    fig.update_yaxes(title_text=left_sensor, secondary_y=False)
    fig.update_yaxes(title_text=right_sensor, secondary_y=True)

    fig.show()


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    # Check for --dual flag
    if "--dual" in args:
        args.remove("--dual")
        if len(args) != 2:
            print("Dual axis mode requires exactly 2 sensors:")
            print("  uv run python visualize.py --dual temperature soilConductivity")
            sys.exit(1)

        left_sensor, right_sensor = args
        print(f"Fetching data for {left_sensor} (left) and {right_sensor} (right)...")
        df = fetch_sensor_data(sensor_tags=[left_sensor, right_sensor])
        print(f"Got {len(df)} readings")
        plot_dual_axis(df, left_sensor, right_sensor)
    else:
        # Single axis mode
        tags = args if args else None

        print("Fetching data from TimescaleDB...")
        df = fetch_sensor_data(sensor_tags=tags)
        print(f"Got {len(df)} readings")

        if tags:
            print(f"Filtered by: {tags}")
        else:
            print("Available sensors:", df["sensor"].unique().tolist() if not df.empty else [])
            print("\nTip: Run with sensor names to filter, e.g.:")
            print("  uv run python visualize.py soilConductivity windDirection")
            print("\nFor dual axis (left/right y-scales):")
            print("  uv run python visualize.py --dual temperature soilConductivity")

        plot_time_series(df)
