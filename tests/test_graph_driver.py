"""Tests for wp6_data.graph.driver — mock AsyncGraphDatabase."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wp6_data.graph.driver import Neo4jConnection


@pytest.fixture()
def conn():
    return Neo4jConnection("bolt://localhost:7687", "neo4j", "pass", "testdb")


class TestConnectClose:
    @pytest.mark.asyncio()
    async def test_connect_creates_driver(self, conn):
        mock_driver = AsyncMock()
        with patch("wp6_data.graph.driver.AsyncGraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            await conn.connect()

        mock_gdb.driver.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "pass"),
            max_connection_lifetime=300,
        )
        mock_driver.verify_connectivity.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_close_shuts_down_driver(self, conn):
        mock_driver = AsyncMock()
        with patch("wp6_data.graph.driver.AsyncGraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            await conn.connect()
            await conn.close()

        mock_driver.close.assert_awaited_once()
        assert conn._driver is None

    @pytest.mark.asyncio()
    async def test_close_without_connect_is_noop(self, conn):
        await conn.close()  # Should not raise


class TestSession:
    @pytest.mark.asyncio()
    async def test_session_without_connect_raises(self, conn):
        with pytest.raises(RuntimeError, match="Driver not connected"):
            async with conn.session():
                pass


class TestEnsureSchema:
    @pytest.mark.asyncio()
    async def test_runs_all_constraints(self, conn):
        mock_session = AsyncMock()

        # driver.session() must return a sync context manager wrapper
        # because Neo4jConnection.session() calls self._driver.session() synchronously
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        mock_driver = MagicMock()
        mock_driver.verify_connectivity = AsyncMock()
        mock_driver.session.return_value = ctx

        with patch("wp6_data.graph.driver.AsyncGraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            await conn.connect()

        constraints = ["CREATE CONSTRAINT a", "CREATE CONSTRAINT b", "CREATE INDEX c"]
        await conn.ensure_schema(constraints)
        assert mock_session.run.await_count == 3
