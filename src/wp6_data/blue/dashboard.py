"""WP6 Blue Dashboard - Neo4j-backed sensor visualization."""

import os
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase

from wp6_data.shared import (
    make_dual_axis_chart,
    make_line_chart,
    prepare_comparison,
    render_compare_form,
    render_date_filter,
    render_page,
    resolve_date_range,
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
        <p><a href="/compare">Custom dual-axis comparison</a></p>
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
    start, end, start_dt, end_dt = resolve_date_range(start, end)

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


@app.get("/compare", response_class=HTMLResponse)
async def compare_form() -> str:
    """Form to select two device/sensor pairs for a custom dual-axis chart."""
    sensors = fetch_available_sensors()

    # Build device -> [sensor tags] mapping
    device_data: dict[str, list[str]] = {}
    for s in sensors:
        device_data.setdefault(s["device"], [])
        if s["sensor"] not in device_data[s["device"]]:
            device_data[s["device"]].append(s["sensor"])

    form_html = render_compare_form(device_data, action_url="/compare/chart")
    content = f"""
        <h1>Custom Compare</h1>
        <p>Select two device/sensor combinations to plot on a dual y-axis chart.</p>
        {form_html}
    """

    return render_page("Custom Compare - WP6 Blue", content, show_back_link=True)


@app.get("/compare/chart", response_class=HTMLResponse)
async def compare_chart(
    left_device: str = Query(...),
    left_measurement: str = Query(...),
    right_device: str = Query(""),
    right_measurement: str = Query(""),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Render a comparison chart for one or two device/sensor pairs."""
    has_right = bool(right_device and right_measurement)

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    left_df = fetch_data(sensor_tags=[left_measurement], start=start_dt, end=end_dt)
    if not left_df.empty:
        left_df = left_df[left_df["device"] == left_device]

    if has_right:
        right_df = fetch_data(sensor_tags=[right_measurement], start=start_dt, end=end_dt)
        if not right_df.empty:
            right_df = right_df[right_df["device"] == right_device]
    else:
        right_df = pd.DataFrame(columns=["device", "sensor", "time", "value"])

    left_label = f"{left_device} | {left_measurement}"
    right_label = f"{right_device} | {right_measurement}" if has_right else ""
    df, left_label, right_label = prepare_comparison(
        left_df, right_df, left_label, right_label,
    )

    extra_params: dict[str, str] = {
        "left_device": left_device,
        "left_measurement": left_measurement,
    }
    if has_right:
        extra_params["right_device"] = right_device
        extra_params["right_measurement"] = right_measurement
    filter_html = render_date_filter(start, end, extra_params=extra_params)

    if df.empty:
        return render_page(
            "Compare - WP6 Blue", filter_html + "<h1>No data found</h1>",
            show_back_link=True, back_url="/compare",
        )

    if has_right:
        fig = make_dual_axis_chart(df, left_label, right_label)
    else:
        fig = make_line_chart(df, title=left_label)
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color:#666; font-size:0.9em;">{len(df):,} data points</p>'

    return render_page(
        "Compare - WP6 Blue",
        filter_html + stats_html + chart_html,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/compare",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
