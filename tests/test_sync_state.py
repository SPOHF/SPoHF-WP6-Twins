"""Tests for wp6_data.sync.state — mock psycopg AsyncConnection."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from wp6_data.sync.state import SyncStateManager


@pytest.fixture()
def state(mock_db_conn):
    return SyncStateManager(mock_db_conn, "yookr-data")


def _set_fetchone(mock_db_conn, row):
    """Configure mock_db_conn's cursor to return a specific row from fetchone."""
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=row)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=cursor)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db_conn.cursor = MagicMock(return_value=ctx)
    return cursor


class TestGetLastTimestamp:
    @pytest.mark.asyncio()
    async def test_stored_timestamp_returned(self, mock_db_conn, state):
        stored = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        _set_fetchone(mock_db_conn, {"last_timestamp": stored})

        ts, is_initial = await state.get_last_timestamp_with_status()
        assert ts == stored
        assert is_initial is False

    @pytest.mark.asyncio()
    async def test_default_lookback_on_missing_record(self, mock_db_conn, state):
        _set_fetchone(mock_db_conn, None)

        before = datetime.now(UTC)
        ts, is_initial = await state.get_last_timestamp_with_status()
        after = datetime.now(UTC)

        assert is_initial is True
        expected_earliest = before - timedelta(hours=24)
        expected_latest = after - timedelta(hours=24)
        assert expected_earliest <= ts <= expected_latest

    @pytest.mark.asyncio()
    async def test_custom_lookback_hours(self, mock_db_conn, state):
        _set_fetchone(mock_db_conn, None)

        before = datetime.now(UTC)
        ts, is_initial = await state.get_last_timestamp_with_status(48)

        expected = before - timedelta(hours=48)
        assert abs((ts - expected).total_seconds()) < 2

    @pytest.mark.asyncio()
    async def test_get_last_timestamp_delegates(self, mock_db_conn, state):
        _set_fetchone(mock_db_conn, None)

        ts = await state.get_last_timestamp()
        assert ts.tzinfo is not None


class TestUpdateTimestamp:
    @pytest.mark.asyncio()
    async def test_update_calls_execute(self, mock_db_conn, state):
        cursor = _set_fetchone(mock_db_conn, None)
        ts = datetime(2024, 7, 1, tzinfo=UTC)
        await state.update_timestamp(ts, 42)

        cursor.execute.assert_awaited()
        call_args = cursor.execute.call_args
        params = call_args[0][1]
        assert params["endpoint"] == "yookr-data"
        assert params["ts"] == ts
        assert params["count"] == 42


class TestRecordRunResult:
    @pytest.mark.asyncio()
    async def test_success_path(self, mock_db_conn, state):
        cursor = _set_fetchone(mock_db_conn, None)
        await state.record_run_result(
            success=True, duration_seconds=1.5, record_count=10
        )
        call_args = cursor.execute.call_args
        params = call_args[0][1]
        assert params["success"] is True
        assert params["duration"] == 1.5
        assert params["records"] == 10

    @pytest.mark.asyncio()
    async def test_failure_path(self, mock_db_conn, state):
        cursor = _set_fetchone(mock_db_conn, None)
        await state.record_run_result(
            success=False,
            duration_seconds=0.5,
            record_count=0,
            error="500 Internal Server Error",
            api_status=500,
            api_error_detail="oops",
        )
        call_args = cursor.execute.call_args
        params = call_args[0][1]
        assert params["success"] is False
        assert params["error"] == "500 Internal Server Error"
        assert params["api_status"] == 500
        assert params["api_detail"] == "oops"
