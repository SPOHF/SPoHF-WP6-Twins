"""E2E: /status coverage reflects what `readings` actually holds.

Coverage is read straight from the `sensors_daily_summary` cagg, which is derived
from `readings`. The retired `daily_coverage` table was insert-only, so it kept
claiming days whose readings had been deleted (e.g. after the yookr-direct purge);
the cagg refreshes from readings, so a deleted day stops reporting.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from wp6_data.blue.deps import MANUAL_SOURCES, fetch_daily_coverage
from wp6_data.db import (
    close_pool,
    init_pool,
    refresh_sensor_summary,
    upsert_readings,
)

pytestmark = pytest.mark.e2e

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"

DEVICE = "e2e-cov-device"
SENSOR = "e2e-cov-temp"
MANUAL_DEVICE = "e2e-cov-manual-device"
MANUAL_SENSOR = "e2e-cov-manual-sensor"


def _noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


def _reading(day: date) -> dict:
    """One automated reading at noon UTC on *day*."""
    return {
        "device_name": DEVICE,
        "sensor_tag": SENSOR,
        "value": "20.0",
        "datetime_measure": _noon(day),
    }


def _days_for(coverage: list[dict], device: str, sensor: str) -> set[date]:
    return {r["day"] for r in coverage if r["device"] == device and r["sensor"] == sensor}


@pytest.mark.e2e
async def test_purged_day_stops_reporting_coverage(tsdb_conn):
    """A day whose readings were deleted must not keep claiming coverage."""
    kept = datetime.now(UTC).date() - timedelta(days=10)
    purged = datetime.now(UTC).date() - timedelta(days=100)

    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            await upsert_readings(conn, [_reading(kept), _reading(purged)])
            await conn.commit()
        await refresh_sensor_summary(pool)

        both = _days_for(await fetch_daily_coverage(), DEVICE, SENSOR)

        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM readings WHERE device_name = %s AND sensor_tag = %s AND time = %s",
                (DEVICE, SENSOR, _noon(purged)),
            )
            await conn.commit()
        await refresh_sensor_summary(pool)

        after = _days_for(await fetch_daily_coverage(), DEVICE, SENSOR)
    finally:
        await close_pool()

    assert {kept, purged} <= both, "both days should report before the purge"
    assert kept in after
    assert purged not in after, "coverage leaked a day whose readings were deleted"


@pytest.mark.e2e
async def test_manual_source_is_tagged_manual(tsdb_conn):
    """A reading carrying a manual `source` is flagged manual=True in coverage.

    Manual uploads write readings with a manual source slug; the cagg groups by
    source, so coverage classifies them without a separate table.
    """
    manual_source = MANUAL_SOURCES[0]
    day = datetime.now(UTC).date() - timedelta(days=3)

    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO readings (time, device_name, sensor_tag, value, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (_noon(day), MANUAL_DEVICE, MANUAL_SENSOR, 1.0, manual_source),
            )
            await conn.commit()
        await refresh_sensor_summary(pool)

        coverage = await fetch_daily_coverage()
    finally:
        await close_pool()

    rows = [
        r for r in coverage
        if r["device"] == MANUAL_DEVICE and r["sensor"] == MANUAL_SENSOR
    ]
    assert len(rows) == 1
    assert rows[0]["manual"] is True
    assert rows[0]["day"] == day
