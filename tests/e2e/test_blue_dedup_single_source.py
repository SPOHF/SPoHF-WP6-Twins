"""E2E: with one automated source, `(device, sensor, time)` identifies a reading.

Replaces the issue-026 coexistence test. `project` is gone, so the dedup key is
back to three columns and re-ingesting an instant must UPDATE rather than insert.

This is load-bearing for the sync, not a formality: `SpoHFClient.fetch_window`
bisects any window past the relay's 10k result cap and re-emits the truncated
attempt's rows, and the relay's offset pagination returns duplicates of its own.
A backfill therefore upserts the same reading several times by design.
"""

from datetime import UTC, datetime, timedelta

import pytest

from wp6_data.db import close_pool, init_pool, upsert_readings

pytestmark = pytest.mark.e2e

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"
DEVICE = "e2e-dedup-dev"
SENSOR = "e2e-dedup-temp"
TS = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _reading(value: str, ts: datetime = TS) -> dict:
    return {
        "device_name": DEVICE, "sensor_tag": SENSOR, "value": value,
        "datetime_measure": ts,
    }


async def _rows(pool) -> list[tuple]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT time, value FROM readings "
            "WHERE device_name = %s AND sensor_tag = %s ORDER BY time",
            (DEVICE, SENSOR),
        )
        return await cur.fetchall()


@pytest.mark.e2e
async def test_same_instant_updates_in_place(tsdb_conn):
    """Re-upserting one instant never yields a second row, and reports created=0.

    The created count comes from `RETURNING (xmax = 0)`, which only PostgreSQL can
    evaluate — so this guards the real SQL, not just the counting logic.
    """
    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            upserted, created = await upsert_readings(conn, [_reading("10.0")])
            await conn.commit()
        assert (upserted, created) == (1, 1), "first insert should count as created"
        assert await _rows(pool) == [(TS, 10.0)]

        async with pool.connection() as conn:
            upserted, created = await upsert_readings(conn, [_reading("11.0")])
            await conn.commit()
        assert (upserted, created) == (1, 0), "conflict-update must not count as created"
        assert await _rows(pool) == [(TS, 11.0)], "duplicate row instead of in-place update"
    finally:
        await close_pool()


@pytest.mark.e2e
async def test_repeated_batch_is_idempotent(tsdb_conn):
    """A bisected re-fetch replays whole batches; row count must not grow."""
    later = TS + timedelta(minutes=10)
    batch = [_reading("10.0"), _reading("12.0", later)]

    pool = await init_pool(TSDB_DSN)
    try:
        for _ in range(3):
            async with pool.connection() as conn:
                await upsert_readings(conn, batch)
                await conn.commit()

        assert await _rows(pool) == [(TS, 10.0), (later, 12.0)]
    finally:
        await close_pool()


@pytest.mark.e2e
async def test_distinct_instants_coexist(tsdb_conn):
    """Different timestamps are different readings — dedup must not collapse them."""
    later = TS + timedelta(seconds=1)

    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            await upsert_readings(conn, [_reading("10.0"), _reading("20.0", later)])
            await conn.commit()

        assert await _rows(pool) == [(TS, 10.0), (later, 20.0)]
    finally:
        await close_pool()
