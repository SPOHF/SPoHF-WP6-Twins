"""E2E: sync run history + streak/clear-on-success against real TimescaleDB.

Exercises the write path (SyncStateManager.record_run_result) end to end: one row
per run lands in sync_run_history, a success clears the transient error and the
failure streak, and the enriched metrics query aggregates it (7-day SLA, sparkline).
"""

import pytest
from psycopg.rows import dict_row

from wp6_data.db import close_pool, init_pool
from wp6_data.db.queries import fetch_sync_metrics_rows
from wp6_data.sync.state import SyncStateManager

pytestmark = pytest.mark.e2e

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"
EP = "e2e-sync-hist"


@pytest.fixture()
async def _clean():
    pool = await init_pool(TSDB_DSN)
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM sync_metadata WHERE endpoint = %s", (EP,))
        await conn.execute("DELETE FROM sync_run_history WHERE endpoint = %s", (EP,))
        await conn.commit()
    yield pool
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM sync_metadata WHERE endpoint = %s", (EP,))
        await conn.execute("DELETE FROM sync_run_history WHERE endpoint = %s", (EP,))
        await conn.commit()
    await close_pool()


@pytest.mark.e2e
async def test_history_row_per_run_and_streak_lifecycle(_clean):
    pool = _clean

    async def run(**kw):
        async with pool.connection() as conn:
            await SyncStateManager(conn, EP).record_run_result(**kw)
            await conn.commit()

    # two failures, then a recovery
    await run(success=False, duration_seconds=1.0, record_count=0,
              error="boom", api_status=500, api_error_detail="detail")
    await run(success=False, duration_seconds=1.0, record_count=0,
              error="boom again", api_status=500)
    await run(success=True, duration_seconds=2.0, record_count=42)

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(*) AS n FROM sync_run_history WHERE endpoint = %s", (EP,)
        )
        assert (await cur.fetchone())["n"] == 3  # one row per run

        await cur.execute(
            "SELECT last_run_success, consecutive_failures, failing_since, "
            "last_error, last_api_status, total_runs, total_failures "
            "FROM sync_metadata WHERE endpoint = %s", (EP,)
        )
        md = await cur.fetchone()

    # The recovering run clears the streak and the stale error, keeps the lifetime count.
    assert md["last_run_success"] is True
    assert md["consecutive_failures"] == 0
    assert md["failing_since"] is None
    assert md["last_error"] is None
    assert md["last_api_status"] is None
    assert md["total_runs"] == 3
    assert md["total_failures"] == 2


@pytest.mark.e2e
async def test_enriched_metrics_aggregate_history(_clean):
    pool = _clean
    async with pool.connection() as conn:
        state = SyncStateManager(conn, EP)
        for i in range(5):
            await state.record_run_result(
                success=(i != 2), duration_seconds=1.0, record_count=100 + i,
            )
        await conn.commit()

    rows = await fetch_sync_metrics_rows(pool)
    row = next(r for r in rows if r["endpoint"] == EP)

    assert row["runs_7d"] == 5
    assert row["ok_7d"] == 4  # one failure
    assert len(row["recent_records"]) == 5      # newest-first, capped at 12
    assert len(row["recent_success"]) == 5      # capped at 20
    assert row["consecutive_failures"] == 0     # last run succeeded
