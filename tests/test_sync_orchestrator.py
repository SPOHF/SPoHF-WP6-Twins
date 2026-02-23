"""Tests for wp6_data.sync.orchestrator — patch SyncStateManager + batch_upsert + mock client."""

from collections import defaultdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wp6_data.sync.orchestrator import SyncOrchestrator, ensure_utc

from .conftest import make_reading

# --- Pure helpers (no mocks) ---


class TestEnsureUtc:
    def test_naive_gets_utc(self):
        dt = datetime(2024, 1, 1, 12, 0)
        result = ensure_utc(dt)
        assert result.tzinfo is UTC

    def test_aware_unchanged(self):
        dt = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        result = ensure_utc(dt)
        assert result is dt


class TestDetermineSyncMode:
    def test_windowed_forced(self):
        assert SyncOrchestrator._determine_sync_mode("windowed", False) is True

    def test_incremental_forced(self):
        assert SyncOrchestrator._determine_sync_mode("incremental", True) is False

    def test_auto_initial_uses_windowed(self):
        assert SyncOrchestrator._determine_sync_mode("auto", True) is True

    def test_auto_subsequent_uses_incremental(self):
        assert SyncOrchestrator._determine_sync_mode("auto", False) is False

    def test_case_insensitive(self):
        assert SyncOrchestrator._determine_sync_mode("WINDOWED", False) is True
        assert SyncOrchestrator._determine_sync_mode("Incremental", True) is False


class TestUpdateSensorStats:
    def test_first_reading(self):
        stats = defaultdict(lambda: {"count": 0, "min": None, "max": None})
        SyncOrchestrator._update_sensor_stats(stats, "temp", "2024-01-01T00:00:00")
        assert stats["temp"]["count"] == 1
        assert stats["temp"]["min"] == "2024-01-01T00:00:00"
        assert stats["temp"]["max"] == "2024-01-01T00:00:00"

    def test_updates_min_max(self):
        stats = defaultdict(lambda: {"count": 0, "min": None, "max": None})
        SyncOrchestrator._update_sensor_stats(stats, "temp", "2024-06-01T00:00:00")
        SyncOrchestrator._update_sensor_stats(stats, "temp", "2024-01-01T00:00:00")
        SyncOrchestrator._update_sensor_stats(stats, "temp", "2024-12-01T00:00:00")
        assert stats["temp"]["count"] == 3
        assert stats["temp"]["min"] == "2024-01-01T00:00:00"
        assert stats["temp"]["max"] == "2024-12-01T00:00:00"

    def test_separate_tags(self):
        stats = defaultdict(lambda: {"count": 0, "min": None, "max": None})
        SyncOrchestrator._update_sensor_stats(stats, "temp", "2024-01-01T00:00:00")
        SyncOrchestrator._update_sensor_stats(stats, "humidity", "2024-02-01T00:00:00")
        assert stats["temp"]["count"] == 1
        assert stats["humidity"]["count"] == 1


class TestReadingToParams:
    def test_converts_reading(self, mock_settings):
        orch = SyncOrchestrator.__new__(SyncOrchestrator)
        orch.settings = mock_settings
        reading = make_reading()
        params = orch._reading_to_params(reading)
        assert params["sensor_id"] == "device-001"
        assert params["project"] == "test-project"
        assert params["sensor_tag"] == "temperature"
        assert params["value"] == "21.5"
        assert "datetime_measure" in params
        assert "api_timestamp" in params


# --- _flush_batch ---


class TestFlushBatch:
    @pytest.mark.asyncio()
    async def test_empty_batch(self, mock_settings):
        orch = SyncOrchestrator.__new__(SyncOrchestrator)
        orch.settings = mock_settings
        session = AsyncMock()
        upserted, created = await orch._flush_batch(session, [])
        assert (upserted, created) == (0, 0)

    @pytest.mark.asyncio()
    async def test_delegates_to_batch_upsert(self, mock_settings):
        orch = SyncOrchestrator.__new__(SyncOrchestrator)
        orch.settings = mock_settings
        session = AsyncMock()
        batch = [{"sensor_id": "x"}]

        with patch(
            "wp6_data.sync.orchestrator.batch_upsert_readings",
            new_callable=AsyncMock,
            return_value=(3, 2),
        ) as mock_upsert:
            upserted, created = await orch._flush_batch(session, batch)

        assert (upserted, created) == (3, 2)
        mock_upsert.assert_awaited_once_with(session, batch)


# --- _sync_endpoint ---


def _make_orchestrator(mock_settings):
    """Create an orchestrator with mocked internals."""
    orch = SyncOrchestrator.__new__(SyncOrchestrator)
    orch.settings = mock_settings
    orch.client = MagicMock()
    orch.neo4j = MagicMock()
    return orch


class TestSyncEndpoint:
    @pytest.mark.asyncio()
    async def test_incremental_calls_fetch_all_since(self, mock_settings):
        mock_settings.sync_mode = "incremental"
        orch = _make_orchestrator(mock_settings)

        session = AsyncMock()
        orch.neo4j.session.return_value.__aenter__ = AsyncMock(return_value=session)
        orch.neo4j.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # No readings returned
        async def empty_iter(*args, **kwargs):
            return
            yield  # noqa: E111 — make it an async generator

        orch.client.fetch_all_since = empty_iter

        with patch("wp6_data.sync.orchestrator.SyncStateManager") as MockState:
            state_inst = AsyncMock()
            state_inst.get_last_timestamp_with_status.return_value = (
                datetime(2024, 1, 1, tzinfo=UTC),
                False,
            )
            MockState.return_value = state_inst

            with patch(
                "wp6_data.sync.orchestrator.batch_upsert_readings",
                new_callable=AsyncMock,
                return_value=(0, 0),
            ):
                count = await orch._sync_endpoint("yookr-data")

        assert count == 0
        state_inst.record_run_result.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_windowed_calls_fetch_all_windowed(self, mock_settings):
        mock_settings.sync_mode = "windowed"
        orch = _make_orchestrator(mock_settings)

        session = AsyncMock()
        orch.neo4j.session.return_value.__aenter__ = AsyncMock(return_value=session)
        orch.neo4j.session.return_value.__aexit__ = AsyncMock(return_value=False)

        async def empty_iter(*args, **kwargs):
            return
            yield

        orch.client.fetch_all_windowed = empty_iter

        with patch("wp6_data.sync.orchestrator.SyncStateManager") as MockState:
            state_inst = AsyncMock()
            state_inst.get_last_timestamp_with_status.return_value = (
                datetime(2024, 1, 1, tzinfo=UTC),
                True,
            )
            MockState.return_value = state_inst

            with patch(
                "wp6_data.sync.orchestrator.batch_upsert_readings",
                new_callable=AsyncMock,
                return_value=(0, 0),
            ):
                count = await orch._sync_endpoint("yookr-data")

        assert count == 0

    @pytest.mark.asyncio()
    async def test_empty_sync_skips_timestamp_update(self, mock_settings):
        mock_settings.sync_mode = "incremental"
        orch = _make_orchestrator(mock_settings)

        session = AsyncMock()
        orch.neo4j.session.return_value.__aenter__ = AsyncMock(return_value=session)
        orch.neo4j.session.return_value.__aexit__ = AsyncMock(return_value=False)

        async def empty_iter(*args, **kwargs):
            return
            yield

        orch.client.fetch_all_since = empty_iter

        with patch("wp6_data.sync.orchestrator.SyncStateManager") as MockState:
            state_inst = AsyncMock()
            state_inst.get_last_timestamp_with_status.return_value = (
                datetime(2024, 1, 1, tzinfo=UTC),
                False,
            )
            MockState.return_value = state_inst

            with patch(
                "wp6_data.sync.orchestrator.batch_upsert_readings",
                new_callable=AsyncMock,
                return_value=(0, 0),
            ):
                await orch._sync_endpoint("yookr-data")

        state_inst.update_timestamp.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_api_error_records_failure(self, mock_settings):
        mock_settings.sync_mode = "incremental"
        orch = _make_orchestrator(mock_settings)

        session = AsyncMock()
        orch.neo4j.session.return_value.__aenter__ = AsyncMock(return_value=session)
        orch.neo4j.session.return_value.__aexit__ = AsyncMock(return_value=False)

        async def error_iter(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "500 Internal Server Error",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(500, text="oops"),
            )
            yield  # noqa: E111

        orch.client.fetch_all_since = error_iter

        with patch("wp6_data.sync.orchestrator.SyncStateManager") as MockState:
            state_inst = AsyncMock()
            state_inst.get_last_timestamp_with_status.return_value = (
                datetime(2024, 1, 1, tzinfo=UTC),
                False,
            )
            MockState.return_value = state_inst

            with pytest.raises(httpx.HTTPStatusError):
                await orch._sync_endpoint("yookr-data")

        state_inst.record_run_result.assert_awaited_once()
        call_kwargs = state_inst.record_run_result.call_args.kwargs
        assert call_kwargs["success"] is False


# --- run() ---


class TestRun:
    @pytest.mark.asyncio()
    async def test_connect_disconnect_lifecycle(self, mock_settings):
        orch = _make_orchestrator(mock_settings)
        orch.neo4j = AsyncMock()

        # Make _sync_endpoint a coroutine that returns 0
        with patch.object(orch, "_sync_endpoint", new_callable=AsyncMock, return_value=5):
            stats = await orch.run()

        orch.neo4j.connect.assert_awaited_once()
        orch.neo4j.close.assert_awaited_once()
        assert stats["total_records"] == 5

    @pytest.mark.asyncio()
    async def test_per_endpoint_error_isolation(self, mock_settings):
        mock_settings.endpoint_list = ["ep1", "ep2"]
        orch = _make_orchestrator(mock_settings)
        orch.neo4j = AsyncMock()

        call_count = 0

        async def side_effect(endpoint):
            nonlocal call_count
            call_count += 1
            if endpoint == "ep1":
                raise RuntimeError("ep1 failed")
            return 10

        with patch.object(orch, "_sync_endpoint", side_effect=side_effect):
            stats = await orch.run()

        assert call_count == 2
        assert len(stats["errors"]) == 1
        assert "ep1" in stats["errors"][0]
        assert stats["endpoints"]["ep2"] == 10
        assert stats["total_records"] == 10

    @pytest.mark.asyncio()
    async def test_stats_aggregation(self, mock_settings):
        mock_settings.endpoint_list = ["ep1", "ep2"]
        orch = _make_orchestrator(mock_settings)
        orch.neo4j = AsyncMock()

        async def side_effect(endpoint):
            return 10 if endpoint == "ep1" else 20

        with patch.object(orch, "_sync_endpoint", side_effect=side_effect):
            stats = await orch.run()

        assert stats["total_records"] == 30
        assert stats["endpoints"] == {"ep1": 10, "ep2": 20}
        assert "duration_seconds" in stats
