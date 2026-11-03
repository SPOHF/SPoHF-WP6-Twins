"""E2E: the shared pool survives its connections being killed server-side.

A TimescaleDB restart terminates every backend, leaving the pool holding dead
idle connections. Without a checkout check, the next request is handed one and
fails with AdminShutdown — a user-facing 500. pg_terminate_backend reproduces
the restart for just the pool's own connection.
"""

import pytest

from tests.e2e.conftest import TSDB_DSN
from wp6_data.db import close_pool, init_pool

pytestmark = pytest.mark.e2e


async def test_query_after_backend_terminated(tsdb_conn):
    pool = await init_pool(TSDB_DSN, min_size=1, max_size=1)
    try:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT pg_backend_pid()")
            (pid,) = await cur.fetchone()

        await tsdb_conn.execute("SELECT pg_terminate_backend(%s)", (pid,))

        async with pool.connection() as conn:
            cur = await conn.execute("SELECT pg_backend_pid()")
            (new_pid,) = await cur.fetchone()
        assert new_pid != pid
    finally:
        await close_pool()
