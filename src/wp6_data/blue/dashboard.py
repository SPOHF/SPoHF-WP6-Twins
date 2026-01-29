"""WP6 Blue Dashboard - Neo4j-backed sensor visualization."""

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase

from wp6_data.shared import (
    default_date_range,
    make_dual_axis_chart,
    make_line_chart,
    render_date_filter,
    render_page,
)

load_dotenv()

app = FastAPI(title="WP6 Blue - Sensor Dashboard")

# Serve static files (logo, etc.) from project root
# __file__ is src/wp6_data/blue/dashboard.py, so .parent x4 gets to wp6-data/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if (PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

# Neo4j connection from environment
NEO4J_URI = os.getenv("WP6_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("WP6_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("WP6_NEO4J_PASSWORD", "localdevpassword")


def get_driver() -> GraphDatabase.driver.__class__:
    """Get Neo4j driver instance."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def fetch_data(
    sensor_tags: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50000,
) -> pd.DataFrame:
    """Fetch sensor readings from Neo4j."""
    with get_driver() as driver, driver.session() as session:
        conditions = []
        if sensor_tags:
            conditions.append("s.tag IN $tags")
        if start:
            conditions.append("r.datetime_measure >= $start")
        if end:
            conditions.append("r.datetime_measure <= $end")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
            {where}
            RETURN d.device_name AS device, s.tag AS sensor,
                   r.datetime_measure AS time, r.value AS value
            ORDER BY r.datetime_measure
            LIMIT $limit
            """
        result = session.run(
            query, tags=sensor_tags, start=start, end=end, limit=limit,
        )
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
    sensor_tags: dict[str, int] = {}
    for s in sensors:
        tag = s["sensor"]
        if tag not in sensor_tags:
            sensor_tags[tag] = 0
        sensor_tags[tag] += s["readings"]

    sensor_list = "".join(
        f'<li><a href="/chart/{tag}">{tag}</a> ({count:,} readings)</li>'
        for tag, count in sorted(sensor_tags.items(), key=lambda x: -x[1])
    )

    content = f"""
        <h1>WP6 Blue - Sensor Dashboard</h1>
        <h2>Available Sensors</h2>
        <ul>{sensor_list}</ul>
        <h2>Compare Sensors</h2>
        <p>
            <a href="/chart/soilConductivity,temperature?dual=true">EC vs temp (dual axis)</a>
        </p>
    """

    return render_page("WP6 Blue - Sensor Dashboard", content)


@app.get("/chart/{sensors}", response_class=HTMLResponse)
async def chart(
    sensors: str,
    dual: bool = Query(False, description="Use dual y-axis for 2 sensors"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Render chart for specified sensors."""
    default_start, default_end = default_date_range()
    start = start or default_start
    end = end or default_end
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    sensor_list = [s.strip() for s in sensors.split(",")]
    df = fetch_data(sensor_tags=sensor_list, start=start_dt, end=end_dt)

    filter_html = render_date_filter(start, end)

    if df.empty:
        return render_page(
            f"{sensors} - WP6 Blue",
            filter_html + "<h1>No data found</h1>",
            show_back_link=True,
        )

    if dual and len(sensor_list) == 2:
        fig = make_dual_axis_chart(df, sensor_list[0], sensor_list[1])
    else:
        fig = make_line_chart(df)

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    return render_page(
        f"{sensors} - WP6 Blue",
        filter_html + chart_html,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
