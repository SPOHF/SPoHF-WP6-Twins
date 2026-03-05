"""Shared fixtures for e2e tests requiring a real TimescaleDB instance."""

import psycopg
import pytest_asyncio

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"
E2E_PREFIX = "e2e-"


@pytest_asyncio.fixture()
async def tsdb_conn():
    """Async psycopg connection for e2e tests. Fails hard if TimescaleDB is unreachable."""
    try:
        conn = await psycopg.AsyncConnection.connect(TSDB_DSN)
    except Exception as exc:
        raise RuntimeError(
            f"TimescaleDB is not reachable at {TSDB_DSN}. "
            "Start it with: docker compose -f docker-compose.blue.yml up -d"
        ) from exc
    yield conn
    await conn.close()


async def _delete_e2e_data(conn) -> None:
    """Delete all rows whose identifying properties start with the e2e prefix."""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM readings WHERE device_name LIKE %(prefix)s",
            {"prefix": f"{E2E_PREFIX}%"},
        )
        await cur.execute(
            "DELETE FROM daily_coverage WHERE device_name LIKE %(prefix)s",
            {"prefix": f"{E2E_PREFIX}%"},
        )
        await cur.execute(
            "DELETE FROM sync_metadata WHERE endpoint LIKE %(prefix)s",
            {"prefix": f"{E2E_PREFIX}%"},
        )
    await conn.commit()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_e2e_data(tsdb_conn):
    """Delete all e2e-prefixed data before and after each test."""
    await _delete_e2e_data(tsdb_conn)
    yield
    await _delete_e2e_data(tsdb_conn)
