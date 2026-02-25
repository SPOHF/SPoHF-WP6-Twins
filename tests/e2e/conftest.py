"""Shared fixtures for e2e tests requiring a real Neo4j instance."""

import pytest_asyncio
from neo4j import AsyncGraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "localdevpassword"

E2E_PREFIX = "e2e-"


@pytest_asyncio.fixture()
async def neo4j_driver():
    """Async Neo4j driver for e2e tests. Fails hard if Neo4j is unreachable."""
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        await driver.verify_connectivity()
    except Exception as exc:
        await driver.close()
        raise RuntimeError(
            f"Neo4j is not reachable at {NEO4J_URI}. "
            "Start it with: docker compose up -d"
        ) from exc
    yield driver
    await driver.close()


async def _delete_e2e_nodes(driver) -> None:
    """Delete all nodes whose identifying properties start with the e2e prefix."""
    async with driver.session() as session:
        # Delete readings linked to e2e sensors
        await session.run(
            "MATCH (s:Sensor) WHERE s.tag STARTS WITH $prefix "
            "OPTIONAL MATCH (s)-[:RECORDED]->(r:Reading) DETACH DELETE r",
            prefix=E2E_PREFIX,
        )
        # Delete sensors
        await session.run(
            "MATCH (s:Sensor) WHERE s.tag STARTS WITH $prefix DETACH DELETE s",
            prefix=E2E_PREFIX,
        )
        # Delete devices
        await session.run(
            "MATCH (d:Device) WHERE d.device_name STARTS WITH $prefix DETACH DELETE d",
            prefix=E2E_PREFIX,
        )
        # Delete projects
        await session.run(
            "MATCH (p:Project) WHERE p.name STARTS WITH $prefix DETACH DELETE p",
            prefix=E2E_PREFIX,
        )
        # Delete daily coverage
        await session.run(
            "MATCH (c:DailyCoverage) WHERE c.device_name STARTS WITH $prefix DELETE c",
            prefix=E2E_PREFIX,
        )
        # Delete sync metadata for e2e endpoints
        await session.run(
            "MATCH (m:SyncMetadata) WHERE m.endpoint STARTS WITH $prefix DELETE m",
            prefix=E2E_PREFIX,
        )


@pytest_asyncio.fixture(autouse=True)
async def cleanup_e2e_data(neo4j_driver):
    """Delete all e2e-prefixed nodes before and after each test."""
    await _delete_e2e_nodes(neo4j_driver)
    yield
    await _delete_e2e_nodes(neo4j_driver)
