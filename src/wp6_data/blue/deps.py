"""Blue dashboard dependencies: config, Neo4j helpers.

All query functions accept an optional ``project`` parameter:
- ``None`` (default) → exclude "yookr-direct" (SPoHF Datalake view)
- A string → include only that project (used by the Yookr view)
"""

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

# Module-level singleton driver — reuses connection pool across all requests
_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

YOOKR_PROJECT = "yookr-direct"


def get_driver():
    """Get the shared Neo4j driver instance."""
    return _driver


def close_driver():
    """Close the shared Neo4j driver (call on app shutdown)."""
    _driver.close()


def _project_clause(project: str | None, *, device_var: str = "d") -> tuple[str, dict]:
    """Build a Cypher project-filter fragment.

    Returns (cypher_fragment, params_dict).
    - project=None  → exclude yookr-direct
    - project=<str> → include only that project
    """
    if project is not None:
        return (
            f"MATCH (p:Project {{name: $project}})-[:HAS_DEVICE]->({device_var})\n",
            {"project": project},
        )
    return (
        f"MATCH (p:Project)-[:HAS_DEVICE]->({device_var})\n"
        f"WHERE p.name <> $excluded_project\n",
        {"excluded_project": YOOKR_PROJECT},
    )


def fetch_data(
    sensor_tags: list[str] | None = None,
    device_names: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50000,
    project: str | None = None,
) -> pd.DataFrame:
    """Fetch sensor readings from Neo4j."""
    with _driver.session() as session:
        proj_clause, proj_params = _project_clause(project)

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
            {proj_clause}
            WITH d
            MATCH (d)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
            {where}
            RETURN d.device_name AS device, s.tag AS sensor,
                   r.datetime_measure AS time, r.value AS value
            ORDER BY r.datetime_measure
            LIMIT $limit
            """
        result = session.run(
            query,
            **proj_params,
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


def fetch_available_sensors(project: str | None = None) -> list[dict[str, Any]]:
    """Get list of sensors with reading counts and date range."""
    with _driver.session() as session:
        proj_clause, proj_params = _project_clause(project)

        result = session.run(
            f"""
                {proj_clause}
                WITH d
                MATCH (d)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
                RETURN d.device_name AS device, s.tag AS sensor, count(r) AS readings,
                       min(r.datetime_measure) AS earliest,
                       max(r.datetime_measure) AS latest
                ORDER BY readings DESC
            """,
            **proj_params,
        )
        records = []
        for r in result:
            rec = dict(r)
            if rec.get("earliest"):
                rec["earliest"] = rec["earliest"].to_native()
            if rec.get("latest"):
                rec["latest"] = rec["latest"].to_native()
            records.append(rec)
        return records


def fetch_daily_coverage(project: str | None = None) -> list[dict[str, Any]]:
    """Get distinct days with data per device+sensor from DailyCoverage nodes."""
    with _driver.session() as session:
        proj_clause, proj_params = _project_clause(project)

        result = session.run(
            f"""
            {proj_clause}
            WITH d
            MATCH (c:DailyCoverage)
            WHERE c.device_name = d.device_name
            RETURN c.device_name AS device, c.sensor_tag AS sensor, c.day AS day
            ORDER BY sensor, device, day
        """,
            **proj_params,
        )
        records = []
        for r in result:
            rec = dict(r)
            if rec.get("day"):
                rec["day"] = rec["day"].to_native()
            records.append(rec)
        return records


def fetch_sync_metrics() -> list[dict[str, Any]]:
    """Fetch sync metadata for all endpoints from Neo4j."""
    with _driver.session() as session:
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
            if rec.get("last_run_at"):
                rec["last_run_at"] = rec["last_run_at"].to_native()
            if rec.get("last_data_timestamp"):
                rec["last_data_timestamp"] = rec["last_data_timestamp"].to_native()
            metrics.append(rec)
        return metrics
