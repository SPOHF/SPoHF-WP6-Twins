"""Tests for wp6_data.sync.state — mock AsyncSession + neo4j DateTime."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from wp6_data.sync.state import SyncStateManager


@pytest.fixture()
def state(mock_neo4j_session):
    return SyncStateManager(mock_neo4j_session, "yookr-data")


class TestGetLastTimestamp:
    @pytest.mark.asyncio()
    async def test_stored_timestamp_returned(self, mock_neo4j_session, state):
        stored = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        neo4j_dt = MagicMock()
        neo4j_dt.to_native.return_value = stored

        record = {"ts": neo4j_dt}
        result = AsyncMock()
        result.single.return_value = record
        mock_neo4j_session.run.return_value = result

        ts, is_initial = await state.get_last_timestamp_with_status()
        assert ts == stored
        assert is_initial is False

    @pytest.mark.asyncio()
    async def test_default_lookback_on_missing_record(self, mock_neo4j_session, state):
        result = AsyncMock()
        result.single.return_value = None
        mock_neo4j_session.run.return_value = result

        before = datetime.now(UTC)
        ts, is_initial = await state.get_last_timestamp_with_status()
        after = datetime.now(UTC)

        assert is_initial is True
        expected_earliest = before - timedelta(hours=24)
        expected_latest = after - timedelta(hours=24)
        assert expected_earliest <= ts <= expected_latest

    @pytest.mark.asyncio()
    async def test_custom_lookback_hours(self, mock_neo4j_session, state):
        result = AsyncMock()
        result.single.return_value = None
        mock_neo4j_session.run.return_value = result

        before = datetime.now(UTC)
        ts, is_initial = await state.get_last_timestamp_with_status(48)

        expected = before - timedelta(hours=48)
        assert abs((ts - expected).total_seconds()) < 2

    @pytest.mark.asyncio()
    async def test_get_last_timestamp_delegates(self, mock_neo4j_session, state):
        result = AsyncMock()
        result.single.return_value = None
        mock_neo4j_session.run.return_value = result

        ts = await state.get_last_timestamp()
        assert ts.tzinfo is not None


class TestUpdateTimestamp:
    @pytest.mark.asyncio()
    async def test_update_params(self, mock_neo4j_session, state):
        ts = datetime(2024, 7, 1, tzinfo=UTC)
        await state.update_timestamp(ts, 42)

        mock_neo4j_session.run.assert_awaited()
        call_kwargs = mock_neo4j_session.run.call_args.kwargs
        assert call_kwargs["endpoint"] == "yookr-data"
        assert call_kwargs["ts"] == ts.isoformat()
        assert call_kwargs["count"] == 42


class TestRecordRunResult:
    @pytest.mark.asyncio()
    async def test_success_path(self, mock_neo4j_session, state):
        await state.record_run_result(
            success=True, duration_seconds=1.5, record_count=10
        )
        call_kwargs = mock_neo4j_session.run.call_args.kwargs
        assert call_kwargs["success"] is True
        assert call_kwargs["duration"] == 1.5
        assert call_kwargs["records"] == 10

    @pytest.mark.asyncio()
    async def test_failure_path(self, mock_neo4j_session, state):
        await state.record_run_result(
            success=False,
            duration_seconds=0.5,
            record_count=0,
            error="500 Internal Server Error",
            api_status=500,
            api_error_detail="oops",
        )
        call_kwargs = mock_neo4j_session.run.call_args.kwargs
        assert call_kwargs["success"] is False
        assert call_kwargs["error"] == "500 Internal Server Error"
        assert call_kwargs["api_status"] == 500
        assert call_kwargs["api_detail"] == "oops"
