"""E2E: round-trip the risk cache through the real wp6_red TSDB (issue 015)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN
from wp6_data.red.risk import store
from wp6_data.red.risk.engine import RiskEpisodeRecord, RiskEvaluation, SectionState
from wp6_data.red.tsdb import ensure_schema_red

pytestmark = pytest.mark.e2e

WIRE = "e2e-WS"
START = datetime(2026, 5, 26, tzinfo=UTC)
END = datetime(2026, 5, 27, tzinfo=UTC)


async def _purge(conn) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM risk_episodes WHERE wire LIKE 'e2e-%'")
        await cur.execute("DELETE FROM risk_state WHERE wire LIKE 'e2e-%'")
    await conn.commit()


@pytest_asyncio.fixture()
async def red_pool(red_tsdb_conn):
    pool = AsyncConnectionPool(RED_TSDB_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    await ensure_schema_red(pool)
    await _purge(red_tsdb_conn)
    try:
        yield pool
    finally:
        await pool.close()
        await _purge(red_tsdb_conn)


def _evaluation(*, with_episode: bool) -> RiskEvaluation:
    episodes = []
    if with_episode:
        episodes = [RiskEpisodeRecord(
            height=1, label="Kop", risk="vpd",
            start=pd.Timestamp("2026-05-26T12:00:00", tz="UTC"),
            end=None, peak=0.4, thresholds={"band_max_kpa": 1.2},
        )]
    return RiskEvaluation(
        states=[SectionState(
            height=1, label="Kop", height_dli=0.5, vpd_latest=1.6,
            vpd_in_band=False, wet_hours_latest=0.0, fungal_active=False,
            co2_latest=350.0, co2_depleted=True,
            canopy_deficit=True,
        )],
        episodes=episodes,
    )


async def test_round_trip_state_and_episode(red_pool):
    await store.persist_build(red_pool, WIRE, START, END, _evaluation(with_episode=True))

    state = await store.read_state(red_pool, WIRE)
    assert len(state) == 1
    assert state[0]["canopy_deficit"] is True
    assert state[0]["vpd_in_band"] is False
    assert state[0]["co2_depleted"] is True
    assert state[0]["co2_latest"] == 350.0

    eps = await store.read_episodes(red_pool, WIRE, START, END)
    assert len(eps) == 1
    assert eps[0]["risk"] == "vpd"
    assert eps[0]["end_time"] is None  # open episode
    assert eps[0]["thresholds"] == {"band_max_kpa": 1.2}  # threshold-set stamped


async def test_rebuild_replaces_the_range(red_pool):
    await store.persist_build(red_pool, WIRE, START, END, _evaluation(with_episode=True))
    # Rebuild the same range with no episodes -> the range is cleared.
    await store.persist_build(red_pool, WIRE, START, END, _evaluation(with_episode=False))
    assert await store.read_episodes(red_pool, WIRE, START, END) == []
    # State is still present (upserted, not deleted).
    assert len(await store.read_state(red_pool, WIRE)) == 1


async def test_last_built_at_set_after_build(red_pool):
    assert await store.last_built_at(red_pool, WIRE) is None
    await store.persist_build(red_pool, WIRE, START, END, _evaluation(with_episode=False))
    assert await store.last_built_at(red_pool, WIRE) is not None
