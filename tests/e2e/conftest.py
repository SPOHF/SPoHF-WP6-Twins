"""Shared fixtures for e2e tests requiring a real TimescaleDB instance."""

import os

# Blue is an authenticated twin (require_auth=True), so building its app
# enters a lifespan that runs OIDC startup. e2e runs in a clean env with no
# OIDC secrets and no reachable issuer; dev-auth mode makes startup_oidc
# short-circuit before any secret check or network call. setdefault so a
# real OIDC env still wins. Must be set before the blue app is imported.
os.environ.setdefault("WP6_OIDC_DEV_AUTH", "true")

import psycopg  # noqa: E402
import pytest_asyncio  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402

from wp6_data.db.schema import ensure_schema  # noqa: E402

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"
RED_TSDB_DSN = "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red"
E2E_PREFIX = "e2e-"
_TSDB_HINT = (
    "Start it with: docker compose -f docker-compose.tsdb.yml up -d "
    "(use `down -v` once if you have an old volume without the wp6_red database)"
)


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _bootstrap_blue_schema():
    """Create blue tables once per session so cleanup_e2e_data has something to delete from."""
    pool = AsyncConnectionPool(TSDB_DSN, min_size=1, max_size=1, open=False)
    await pool.open()
    try:
        await ensure_schema(pool)
        yield
    finally:
        await pool.close()


@pytest_asyncio.fixture()
async def tsdb_conn():
    """Async psycopg connection for e2e tests. Fails hard if TimescaleDB is unreachable."""
    try:
        conn = await psycopg.AsyncConnection.connect(TSDB_DSN)
    except Exception as exc:
        raise RuntimeError(
            f"TimescaleDB is not reachable at {TSDB_DSN}. {_TSDB_HINT}"
        ) from exc
    yield conn
    await conn.close()


@pytest_asyncio.fixture()
async def red_tsdb_conn():
    """Async psycopg connection to the red wp6_red database."""
    try:
        conn = await psycopg.AsyncConnection.connect(RED_TSDB_DSN)
    except Exception as exc:
        raise RuntimeError(
            f"Red TimescaleDB is not reachable at {RED_TSDB_DSN}. {_TSDB_HINT}"
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
