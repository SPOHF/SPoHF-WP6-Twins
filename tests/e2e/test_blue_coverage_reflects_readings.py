"""E2E: /status coverage reflects what `readings` actually holds.

`daily_coverage` is insert-only — the sync adds a (device, sensor, day) row as it
ingests, and nothing ever removes one. So it cannot be trusted alone: after the
yookr-direct purge it still claimed days whose rows were deleted. `fetch_daily_coverage`
therefore cross-checks each automated day against the `sensors_daily_summary` cagg,
which is derived from `readings` and tells the truth.

(This replaces the issue-022 source-attribution test. That leak — one source's days
showing under the other's view — became unreachable when the data-source toggle was
removed, but the day-level cagg join it introduced now serves this purpose instead.)
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from wp6_data.blue.deps import MANUAL_SOURCES, fetch_daily_coverage
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


def _coverage_row(device: str, sensor: str, day: date, source: str) -> dict:
    return {
        "device_name": device, "sensor_tag": sensor,
        "source": source, "day": day.isoformat(),
    }


def _days_for(coverage: list[dict], device: str, sensor: str) -> set[date]:
    return {r["day"] for r in coverage if r["device"] == device and r["sensor"] == sensor}


@pytest.mark.e2e
async def test_purged_day_stops_reporting_coverage(tsdb_conn):
    """A day whose readings were deleted must not keep claiming coverage.

    This is exactly what the yookr-direct purge does to `daily_coverage`.
    """
    kept = datetime.now(UTC).date() - timedelta(days=10)
    purged = datetime.now(UTC).date() - timedelta(days=100)

    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            await upsert_readings(conn, [_reading(kept), _reading(purged)])
            await upsert_daily_coverage(
                conn,
                [
                    _coverage_row(DEVICE, SENSOR, kept, "unknown"),
                    _coverage_row(DEVICE, SENSOR, purged, "unknown"),
                ],
            )
            await conn.commit()
        await refresh_sensor_summary(pool)

        both = _days_for(await fetch_daily_coverage(), DEVICE, SENSOR)

        # Purge one day's readings, leaving its daily_coverage row behind.
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
    assert purged not in after, "stale daily_coverage row leaked a day with no readings"


@pytest.mark.e2e
async def test_manual_coverage_is_visible_without_the_cagg(tsdb_conn):
    """Manual rows are flagged straight off `daily_coverage.source`.

    They never depend on the cagg join, so a manual upload shows on /status the
    moment it lands rather than after the next refresh cycle.
    """
    manual_source = MANUAL_SOURCES[0]
    day = datetime.now(UTC).date() - timedelta(days=3)

    pool = await init_pool(TSDB_DSN)
    try:
        async with pool.connection() as conn:
            await upsert_daily_coverage(
                conn, [_coverage_row(MANUAL_DEVICE, MANUAL_SENSOR, day, manual_source)],
            )
            await conn.commit()

        coverage = await fetch_daily_coverage()
    finally:
        await close_pool()

    rows = [
        r for r in coverage
        if r["device"] == MANUAL_DEVICE and r["sensor"] == MANUAL_SENSOR
    ]
    assert len(rows) == 1, "manual coverage must show without any readings/cagg entry"
    assert rows[0]["manual"] is True
    assert rows[0]["day"] == day
