"""E2E: the project-aware dedup key lets the two sources coexist (issue 026).

With the unique key `(device, sensor, time, project)`, a yookr-direct and a
spohf-datalake reading for the same instant produce TWO rows instead of one
absorbing the other — while same-`(device, sensor, time, project)` still dedups.
"""

from datetime import UTC, datetime

import pytest

from wp6_data.db import close_pool, init_pool, upsert_readings

pytestmark = pytest.mark.e2e

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"
DEVICE = "e2e-coexist-dev"
SENSOR = "e2e-coexist-temp"
TS = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _reading(project: str, value: str) -> dict:
    return {
        "device_name": DEVICE, "sensor_tag": SENSOR, "value": value,
        "project": project, "datetime_measure": TS,
    }


@pytest.mark.e2e
async def test_two_projects_coexist_same_timestamp(tsdb_conn):
    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            await upsert_readings(conn, [_reading("yookr-direct", "10.0")])
            await upsert_readings(conn, [_reading("spohf-datalake", "20.0")])
            await conn.commit()

        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT project, value FROM readings "
                "WHERE device_name = %s AND sensor_tag = %s ORDER BY project",
                (DEVICE, SENSOR),
            )
            rows = await cur.fetchall()
            # Coexisting: one row per project, neither absorbed.
            assert rows == [("spohf-datalake", 20.0), ("yookr-direct", 10.0)]

        # Same (device, sensor, time, project) still dedups → UPDATE, not a 3rd row.
        async with pool.connection() as conn:
            await upsert_readings(conn, [_reading("yookr-direct", "11.0")])
            await conn.commit()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT project, value FROM readings "
                "WHERE device_name = %s AND sensor_tag = %s ORDER BY project",
                (DEVICE, SENSOR),
            )
            rows = await cur.fetchall()
            assert rows == [("spohf-datalake", 20.0), ("yookr-direct", 11.0)]
    finally:
        await close_pool()
