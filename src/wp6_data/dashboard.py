"""Simple dashboard for sensor data visualization."""

import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase
from plotly.subplots import make_subplots

load_dotenv()


app = FastAPI(title="WP6 Sensor Dashboard")

# Serve static files (logo, etc.) from project root
# __file__ is src/wp6_data/dashboard.py, so .parent.parent.parent gets to wp6-data/
PROJECT_ROOT = Path(__file__).parent.parent.parent
if (PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

# Neo4j connection from environment
NEO4J_URI = os.getenv("WP6_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("WP6_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("WP6_NEO4J_PASSWORD", "localdevpassword")


def get_driver() -> GraphDatabase.driver.__class__:
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def fetch_data(sensor_tags: list[str] | None = None, limit: int = 50000) -> pd.DataFrame:
    """Fetch sensor readings from Neo4j."""
    with get_driver() as driver, driver.session() as session:
        tag_filter = "WHERE s.tag IN $tags" if sensor_tags else ""
        query = f"""
            MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
            {tag_filter}
            RETURN d.device_name AS device, s.tag AS sensor,
                   r.datetime_measure AS time, r.value AS value
            ORDER BY r.datetime_measure
            LIMIT $limit
            """
        result = session.run(query, tags=sensor_tags, limit=limit)
        records = []
        for r in result:
            rec = dict(r)
            if rec.get("time"):
                rec["time"] = rec["time"].to_native()
            records.append(rec)

    df = pd.DataFrame(records)
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.sort_values("time")
    return df

def fetch_available_sensors() -> list[dict[str, Any]]:
    """Get list of sensors with reading counts."""
    with get_driver() as driver, driver.session() as session:
        result = session.run("""
                MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
                RETURN d.device_name AS device, s.tag AS sensor, count(r) AS readings
                ORDER BY readings DESC
            """)
        return [dict(r) for r in result]


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for k8s probes (doesn't hit Neo4j)."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    """Dashboard home page."""
    sensors = fetch_available_sensors()

    # Group sensors by tag
    sensor_tags = {}
    for s in sensors:
        tag = s["sensor"]
        if tag not in sensor_tags:
            sensor_tags[tag] = 0
        sensor_tags[tag] += s["readings"]

    sensor_list = "".join(
        f'<li><a href="/chart/{tag}">{tag}</a> ({count:,} readings)</li>'
        for tag, count in sorted(sensor_tags.items(), key=lambda x: -x[1])
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>WP6 Sensor Dashboard</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; }}
            h1 {{ color: #333; }}
            ul {{ line-height: 1.8; }}
            a {{ color: #0066cc; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .logo {{ margin-bottom: 20px; }}
            .logo img {{ max-height: 80px; }}
            footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }}
        </style>
    </head>
    <body>
        <div class="logo">
            <img src="/static/interreg.png" alt="Interreg Logo">
        </div>
        <h1>WP6 Sensor Dashboard</h1>
        <h2>Available Sensors</h2>
        <ul>{sensor_list}</ul>
        <h2>Compare Sensors</h2>
        <p>
            <a href="/chart/soilConductivity,temperature?dual=true">EC vs temp (dual axis)
            </a>
        </p>
        <footer>
            <img src="/static/interreg.png" alt="Interreg" style="max-height: 60px;">
        </footer>
    </body>
    </html>
    """


@app.get("/chart/{sensors}", response_class=HTMLResponse)
async def chart(
    sensors: str,
    dual: bool = Query(False, description="Use dual y-axis for 2 sensors"),
) -> str:
    """Render chart for specified sensors."""
    sensor_list = [s.strip() for s in sensors.split(",")]
    df = fetch_data(sensor_tags=sensor_list)

    if df.empty:
        return "<h1>No data found</h1>"

    if dual and len(sensor_list) == 2:
        fig = make_dual_axis_chart(df, sensor_list[0], sensor_list[1])
    else:
        fig = make_line_chart(df)

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{sensors} - WP6 Dashboard</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; }}
            .back {{ margin-bottom: 20px; }}
            a {{ color: #0066cc; text-decoration: none; }}
        </style>
    </head>
    <body>
        <div class="back"><a href="/">&larr; Back to Dashboard</a></div>
        {chart_html}
    </body>
    </html>
    """


def make_line_chart(df: pd.DataFrame) -> go.Figure:
    """Create line chart."""
    df["series"] = df["device"] + " | " + df["sensor"]
    fig = px.line(
        df, x="time", y="value", color="series",
        title="Sensor Readings Over Time",
    )
    fig.update_layout(hovermode="x unified", height=600)
    return fig


def make_dual_axis_chart(df: pd.DataFrame, left: str, right: str) -> go.Figure:
    """Create dual y-axis chart."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    left_data = df[df["sensor"] == left]
    right_data = df[df["sensor"] == right]

    for device in left_data["device"].unique():
        d = left_data[left_data["device"] == device]
        fig.add_trace(
            go.Scatter(x=d["time"], y=d["value"], name=f"{device} | {left}", mode="lines"),
            secondary_y=False,
        )

    for device in right_data["device"].unique():
        d = right_data[right_data["device"] == device]
        fig.add_trace(
            go.Scatter(x=d["time"], y=d["value"], name=f"{device} | {right}",
                      mode="lines", line=dict(dash="dash")),
            secondary_y=True,
        )

    fig.update_layout(title=f"{left} vs {right}", hovermode="x unified", height=600)
    fig.update_yaxes(title_text=left, secondary_y=False)
    fig.update_yaxes(title_text=right, secondary_y=True)
    return fig


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
