"""E2E: /status coverage honors the data-source toggle at day granularity.

Regression test for the coverage-attribution leak (issue 022). ``daily_coverage``
has no ``project`` column, so a pair-level visibility match made a sensor's days
show under *either* source-view as long as the (device, sensor) pair appeared in
that view at all — leaking the other source's days. The fix matches at
``(device, sensor, day)`` against the cagg, which groups by ``project``.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from wp6_data.blue.deps import YOOKR_PROJECT, fetch_daily_coverage
from wp6_data.db import (
    close_pool,
    init_pool,
    refresh_sensor_summary,
    upsert_daily_coverage,
    upsert_readings,
)

pytestmark = pytest.mark.e2e

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"

DEVICE = "e2e-cov-device"
SENSOR = "e2e-cov-temp"
DATALAKE_PROJECT = "e2e-datalake"  # any project != yookr-direct = the datalake view


def _reading(project: str, day: date) -> dict:
    """One automated reading at noon UTC on *day* under *project*."""
    ts = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
    return {
        "device_name": DEVICE,
        "sensor_tag": SENSOR,
        "value": "20.0",
        "project": project,
        "datetime_measure": ts,
    }


def _days_for(coverage: list[dict]) -> set[date]:
    """Days reported for our e2e (device, sensor)."""
    return {
        r["day"]
        for r in coverage
        if r["device"] == DEVICE and r["sensor"] == SENSOR
    }


@pytest.mark.e2e
async def test_coverage_days_are_filtered_by_source(tsdb_conn):
    """A sensor fresh in yookr-direct but stale in the datalake must report only
    its own days under each source-view — no cross-source leakage."""
    today = datetime.now(UTC).date()
    stale = today - timedelta(days=100)

    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            # Same (device, sensor): fresh under yookr-direct, stale under datalake.
            await upsert_readings(
                conn,
                [_reading(YOOKR_PROJECT, today), _reading(DATALAKE_PROJECT, stale)],
            )
            # daily_coverage carries no project — both days land as plain
            # automated ('unknown') rows, exactly as the sync would write them.
            await upsert_daily_coverage(
                conn,
                [
                    {"device_name": DEVICE, "sensor_tag": SENSOR,
                     "source": "unknown", "day": today.isoformat()},
                    {"device_name": DEVICE, "sensor_tag": SENSOR,
                     "source": "unknown", "day": stale.isoformat()},
                ],
            )
            await conn.commit()

        # Materialize the cagg so the day-level join sees both buckets.
        await refresh_sensor_summary(pool)

        datalake_days = _days_for(await fetch_daily_coverage(project=None))
        yookr_days = _days_for(await fetch_daily_coverage(project=YOOKR_PROJECT))
    finally:
        await close_pool()

    # Datalake view: only the datalake-owned (stale) day — NOT yookr's fresh day.
    assert stale in datalake_days
    assert today not in datalake_days, "leak: yookr-direct's day shown under datalake"

    # Yookr view: only the yookr-owned (fresh) day — NOT the datalake's stale day.
    assert today in yookr_days
    assert stale not in yookr_days, "leak: datalake's day shown under yookr view"
