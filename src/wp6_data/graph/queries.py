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

// Create Reading (unique by sensor + datetime_measure to avoid duplicates)
MERGE (reading:Reading {
    sensor_id: r.sensor_id,
    tag: r.sensor_tag,
    datetime_measure: datetime(r.datetime_measure)
})
ON CREATE SET
    reading.value = toFloat(r.value),
    reading.raw_value = r.value,
    reading.api_timestamp = datetime(r.api_timestamp),
    reading.synced_at = datetime()
MERGE (s)-[:RECORDED]->(reading)

RETURN count(reading) AS upserted_count
"""


async def batch_upsert_readings(
    session,  # AsyncSession
    readings: list[dict],
) -> int:
    """Upsert a batch of readings to Neo4j.

    Args:
        session: Neo4j async session
        readings: List of reading dicts with keys:
            - sensor_id, project, device_name, sensor_tag
            - value, datetime_measure, api_timestamp

    Returns:
        Number of readings upserted
    """
    if not readings:
        return 0

    result = await session.run(BATCH_UPSERT_QUERY, readings=readings)
    record = await result.single()
    return record["upserted_count"] if record else 0
