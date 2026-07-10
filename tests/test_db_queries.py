"""Tests for wp6_data.db.queries — mock AsyncConnection."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from wp6_data.db.queries import upsert_readings


@pytest.fixture()
def sample_readings():
    return [
        {
            "sensor_id": "d1",
            "device_name": "Dev1",
            "sensor_tag": "temperature",
            "value": "21.5",
            "datetime_measure": "2024-06-15T12:00:00+00:00",
        }
    ]


def _make_conn(inserted: bool = True):
    """Create a mock async connection with cursor context manager.

    ``inserted`` is what ``RETURNING (xmax = 0)`` yields per row — True for a
    fresh insert, False for a conflict-update.
    """
    conn = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=(inserted,))

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=cursor)
    ctx.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=ctx)
    return conn, cursor


class TestUpsertReadings:
    @pytest.mark.asyncio()
    async def test_empty_batch_returns_zeros(self):
        conn = AsyncMock()
        upserted, created = await upsert_readings(conn, [])
        assert (upserted, created) == (0, 0)

    @pytest.mark.asyncio()
    async def test_returns_counts_for_inserts(self, sample_readings):
        conn, cursor = _make_conn(inserted=True)
        upserted, created = await upsert_readings(conn, sample_readings)
        assert (upserted, created) == (1, 1)

    @pytest.mark.asyncio()
    async def test_returns_counts_for_updates(self, sample_readings):
        conn, cursor = _make_conn(inserted=False)
        upserted, created = await upsert_readings(conn, sample_readings)
        assert (upserted, created) == (1, 0)

    @pytest.mark.asyncio()
    async def test_execute_called_per_reading(self, sample_readings):
        conn, cursor = _make_conn(inserted=True)
        await upsert_readings(conn, sample_readings)
        cursor.execute.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_multiple_readings_batch(self):
        readings = [
            {
                "sensor_id": f"d{i}",
                "device_name": "D",
                "sensor_tag": "t",
                "value": str(i),
                "datetime_measure": "2024-01-01T00:00:00+00:00",
            }
            for i in range(5)
        ]
        conn, cursor = _make_conn("INSERT 0 1")
        upserted, created = await upsert_readings(conn, readings)
        assert upserted == 5
        assert created == 5
        assert cursor.execute.await_count == 5
