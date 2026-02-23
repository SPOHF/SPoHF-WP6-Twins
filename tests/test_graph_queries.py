"""Tests for wp6_data.graph.queries — mock AsyncSession."""

from unittest.mock import AsyncMock

import pytest

from wp6_data.graph.queries import batch_upsert_readings


@pytest.fixture()
def sample_readings():
    return [
        {
            "sensor_id": "d1",
            "project": "p1",
            "device_name": "Dev1",
            "sensor_tag": "temperature",
            "value": "21.5",
            "datetime_measure": "2024-06-15T12:00:00+00:00",
            "api_timestamp": "2024-06-15T12:00:01+00:00",
        }
    ]


class TestBatchUpsertReadings:
    @pytest.mark.asyncio()
    async def test_empty_batch_returns_zeros(self):
        session = AsyncMock()
        upserted, created = await batch_upsert_readings(session, [])
        assert (upserted, created) == (0, 0)
        session.run.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_returns_counts_from_record(self, sample_readings):
        session = AsyncMock()
        record = {"upserted_count": 5, "created_count": 3}
        result = AsyncMock()
        result.single.return_value = record
        session.run.return_value = result

        upserted, created = await batch_upsert_readings(session, sample_readings)
        assert (upserted, created) == (5, 3)

    @pytest.mark.asyncio()
    async def test_readings_passed_as_param(self, sample_readings):
        session = AsyncMock()
        result = AsyncMock()
        result.single.return_value = {"upserted_count": 1, "created_count": 1}
        session.run.return_value = result

        await batch_upsert_readings(session, sample_readings)
        session.run.assert_awaited_once()
        call_kwargs = session.run.call_args
        assert call_kwargs.kwargs["readings"] == sample_readings

    @pytest.mark.asyncio()
    async def test_none_record_returns_zeros(self, sample_readings):
        session = AsyncMock()
        result = AsyncMock()
        result.single.return_value = None
        session.run.return_value = result

        upserted, created = await batch_upsert_readings(session, sample_readings)
        assert (upserted, created) == (0, 0)

    @pytest.mark.asyncio()
    async def test_multiple_readings_batch(self):
        readings = [
            {
                "sensor_id": f"d{i}",
                "project": "p",
                "device_name": "D",
                "sensor_tag": "t",
                "value": str(i),
                "datetime_measure": "2024-01-01T00:00:00+00:00",
                "api_timestamp": "2024-01-01T00:00:00+00:00",
            }
            for i in range(5)
        ]
        session = AsyncMock()
        result = AsyncMock()
        result.single.return_value = {"upserted_count": 5, "created_count": 5}
        session.run.return_value = result

        upserted, created = await batch_upsert_readings(session, readings)
        assert upserted == 5

    @pytest.mark.asyncio()
    async def test_query_string_contains_unwind(self, sample_readings):
        session = AsyncMock()
        result = AsyncMock()
        result.single.return_value = {"upserted_count": 1, "created_count": 1}
        session.run.return_value = result

        await batch_upsert_readings(session, sample_readings)
        query = session.run.call_args.args[0]
        assert "UNWIND" in query
