"""Blue dashboard dependencies: config, Neo4j helpers."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# Serve static files (logo, etc.) from project root
# __file__ is src/wp6_data/blue/deps.py, so .parent x4 gets to wp6-data/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Neo4j connection from environment
NEO4J_URI = os.getenv("WP6_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("WP6_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("WP6_NEO4J_PASSWORD", "localdevpassword")


def get_driver() -> GraphDatabase.driver.__class__:
    """Get Neo4j driver instance."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def fetch_data(
    sensor_tags: list[str] | None = None,
    device_names: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50000,
) -> pd.DataFrame:
    """Fetch sensor readings from Neo4j."""
    with get_driver() as driver, driver.session() as session:
        conditions = []
        if sensor_tags:
            conditions.append("s.tag IN $tags")
        if device_names:
            conditions.append("d.device_name IN $devices")
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
            query,
            tags=sensor_tags,
            devices=device_names,
            start=start,
            end=end,
            limit=limit,
        )
        records = []
        for r in result:
            rec = dict(r)
            if rec.get("time"):
                rec["time"] = rec["time"].to_native()
            records.append(rec)

    if not records:
        return pd.DataFrame(columns=["device", "sensor", "time", "value"])
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


def fetch_sync_metrics() -> list[dict[str, Any]]:
    """Fetch sync metadata for all endpoints from Neo4j."""
    with get_driver() as driver, driver.session() as session:
        result = session.run("""
            MATCH (m:SyncMetadata)
            RETURN m.endpoint AS endpoint,
                   m.last_run_at AS last_run_at,
                   m.last_run_success AS last_run_success,
                   m.last_run_duration_seconds AS duration_seconds,
                   m.last_run_records AS records,
                   m.last_error AS error,
                   m.last_api_status AS api_status,
                   m.last_api_error_detail AS api_error_detail,
                   m.total_runs AS total_runs,
                   m.total_failures AS total_failures,
                   m.last_timestamp AS last_data_timestamp
        """)
        metrics = []
        for r in result:
            rec = dict(r)
            # Convert neo4j datetime to python datetime
            if rec.get("last_run_at"):
                rec["last_run_at"] = rec["last_run_at"].to_native()
            if rec.get("last_data_timestamp"):
                rec["last_data_timestamp"] = rec["last_data_timestamp"].to_native()
            metrics.append(rec)
        return metrics
