from typing import Any

from neo4j import AsyncSession

"""Cypher queries for Neo4j operations."""

# Schema constraints and indexes (run once on startup)
CONSTRAINTS = [
    # Unique constraint on Device by sensor_id
    """CREATE CONSTRAINT device_sensor_id IF NOT EXISTS
       FOR (d:Device) REQUIRE d.sensor_id IS UNIQUE""",
    # Composite uniqueness for Sensor (device + tag combination)
    """CREATE CONSTRAINT sensor_device_tag IF NOT EXISTS
       FOR (s:Sensor) REQUIRE (s.device_id, s.tag) IS UNIQUE""",
    # Index on Reading datetime for time-range queries
    """CREATE INDEX reading_datetime IF NOT EXISTS
       FOR (r:Reading) ON (r.datetime_measure)""",
    # Index on Project name
    """CREATE INDEX project_name IF NOT EXISTS
       FOR (p:Project) ON (p.name)""",
    # Unique constraint on DailyCoverage (device + sensor + day)
    """CREATE CONSTRAINT daily_coverage_unique IF NOT EXISTS
       FOR (c:DailyCoverage) REQUIRE (c.device_name, c.sensor_tag, c.day) IS UNIQUE""",
]

# Batch upsert readings with full graph structure
# Creates/merges: Project -> Device -> Sensor -> Reading
BATCH_UPSERT_QUERY = """
UNWIND $readings AS r

// Create or merge Project
MERGE (p:Project {name: r.project})

// Create or merge Device under Project
MERGE (d:Device {sensor_id: r.sensor_id})
ON CREATE SET d.device_name = r.device_name, d.created_at = datetime()
ON MATCH SET d.device_name = r.device_name
MERGE (p)-[:HAS_DEVICE]->(d)

// Create or merge Sensor (unique per device + tag)
MERGE (s:Sensor {device_id: r.sensor_id, tag: r.sensor_tag})
ON CREATE SET s.created_at = datetime()
MERGE (d)-[:HAS_SENSOR]->(s)

// Create or update Reading (unique by sensor + datetime_measure)
MERGE (reading:Reading {
    sensor_id: r.sensor_id,
    tag: r.sensor_tag,
    datetime_measure: datetime(r.datetime_measure)
})
ON CREATE SET
    reading.value = toFloat(r.value),
    reading.raw_value = r.value,
    reading.api_timestamp = datetime(r.api_timestamp),
    reading.synced_at = datetime(),
    reading._created = true
ON MATCH SET
    reading.value = toFloat(r.value),
    reading.raw_value = r.value,
    reading.api_timestamp = datetime(r.api_timestamp),
    reading.updated_at = datetime(),
    reading._created = false
MERGE (s)-[:RECORDED]->(reading)

WITH reading
RETURN
    count(reading) AS upserted_count,
    count(CASE WHEN reading._created THEN 1 END) AS created_count

"""


async def batch_upsert_readings(
    session: AsyncSession,
    readings: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert a batch of readings to Neo4j.

    Args:
        session: Neo4j async session
        readings: List of reading dicts with keys:
            - sensor_id, project, device_name, sensor_tag
            - value, datetime_measure, api_timestamp

    Returns:
        Tuple of (total upserted, newly created)
    """
    if not readings:
        return 0, 0

    result = await session.run(BATCH_UPSERT_QUERY, readings=readings)
    record = await result.single()
    if not record:
        return 0, 0
    return record["upserted_count"], record["created_count"]


UPSERT_DAILY_COVERAGE_QUERY = """
UNWIND $records AS r
MERGE (c:DailyCoverage {device_name: r.device_name, sensor_tag: r.sensor_tag, day: date(r.day)})
RETURN count(c) AS total
"""

REBUILD_DAILY_COVERAGE_QUERY = """
MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading)
WITH DISTINCT d.device_name AS dn, s.tag AS st, date(r.datetime_measure) AS day
MERGE (c:DailyCoverage {device_name: dn, sensor_tag: st, day: day})
RETURN count(c) AS total
"""


async def upsert_daily_coverage(
    session: AsyncSession,
    records: list[dict[str, str]],
) -> int:
    """Upsert DailyCoverage nodes for a batch of (device_name, sensor_tag, day) combos.

    Args:
        session: Neo4j async session
        records: List of dicts with keys: device_name, sensor_tag, day (ISO date string)

    Returns:
        Number of DailyCoverage nodes touched
    """
    if not records:
        return 0
    result = await session.run(UPSERT_DAILY_COVERAGE_QUERY, records=records)
    record = await result.single()
    return record["total"] if record else 0


async def rebuild_daily_coverage(session: AsyncSession) -> int:
    """Rebuild all DailyCoverage nodes by scanning existing Readings.

    Returns:
        Total number of DailyCoverage nodes created/matched
    """
    result = await session.run(REBUILD_DAILY_COVERAGE_QUERY)
    record = await result.single()
    return record["total"] if record else 0
