"""E2E regression: server-side /api/series aggregation against real TSDB.

Guards the alias-collision bug: `time_bucket(...) AS time` shadows
readings.time, and Postgres resolved that name differently in GROUP BY
(input column) vs ORDER BY (output alias) — silently defeating the
bucketing and disordering points. grey-only tests miss this (pandas path),
so this exercises the actual SQL.
"""

import os

import httpx
import pytest
from httpx import ASGITransport

from .conftest import TSDB_DSN

pytestmark = pytest.mark.e2e

DEV = "e2e-aggdev"
SEN = "e2e-aggsensor"

# (iso ts, value) — inserted deliberately OUT OF time order so a missing
# ORDER BY (or one defeated by the alias bug) would show through.
ROWS = [
    ("2026-03-10T12:15:00Z", 5.0),    # bucket C (12:00) — 1 reading
    ("2026-03-10T10:25:00Z", 20.0),   # bucket A (10:00)
    ("2026-03-10T11:50:00Z", 200.0),  # bucket B (11:00)
    ("2026-03-10T10:05:00Z", 10.0),   # bucket A
    ("2026-03-10T10:45:00Z", None),   # bucket A — NULL, excluded from count
    ("2026-03-10T11:10:00Z", 100.0),  # bucket B
    ("2026-03-10T10:55:00Z", 30.0),   # bucket A
]
# bucket A: avg(10,20,30)=20 count 3 ; B: avg(100,200)=150 count 2 ; C: 5 count 1


@pytest.fixture()
async def _seeded(tsdb_conn):
    async with tsdb_conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO readings (time, device_name, sensor_tag, value) "
            "VALUES (%s, %s, %s, %s)",
            [(ts, DEV, SEN, v) for ts, v in ROWS],
        )
    await tsdb_conn.commit()


async def _series(params: str):
    os.environ["WP6_TSDB_URL"] = TSDB_DSN
    from wp6_data.blue.dashboard import app

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True,
    ) as client:
        resp = await client.get(
            f"/api/series?device={DEV}&sensor={SEN}"
            f"&start=2026-03-10&end=2026-03-10{params}"
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_hourly_avg_is_aggregated_sorted_and_counted(_seeded):
    body = await _series("&bkt=60&agg=avg")
    data = body["data"]

    # Real aggregation: 7 raw rows collapse to 3 hourly buckets.
    assert len(data) == 3
    assert body["truncated"] is False

    times = [d["time"] for d in data]
    assert times == sorted(times), f"not time-sorted: {times}"
    assert len(set(times)) == 3  # distinct buckets

    assert [d["count"] for d in data] == [3, 2, 1]
    values = [d["value"] for d in data]
    assert values == pytest.approx([20.0, 150.0, 5.0])

    # Range band: each bucketed point carries the raw min/max extremes.
    # A: min(10,20,30)=10 max=30 ; B: 100/200 ; C: single 5.
    assert [d["min"] for d in data] == pytest.approx([10.0, 100.0, 5.0])
    assert [d["max"] for d in data] == pytest.approx([30.0, 200.0, 5.0])


async def test_raw_path_unaggregated_regression(_seeded):
    body = await _series("")  # no bkt/agg
    assert len(body["data"]) == len(ROWS)
    assert "count" not in body["data"][0]
    # min/max ride along only on bucketed responses.
    assert "min" not in body["data"][0]
    assert "max" not in body["data"][0]
