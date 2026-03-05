"""Tests for wp6_data.db.pool — mock AsyncConnectionPool."""

from unittest.mock import AsyncMock, patch

import pytest

from wp6_data.db.pool import close_pool, get_pool, init_pool


class TestPool:
    @pytest.fixture(autouse=True)
    def _reset_pool(self):
        """Ensure pool is reset before and after each test."""
        import wp6_data.db.pool as pool_mod
        pool_mod._pool = None
        yield
        pool_mod._pool = None

    def test_get_pool_before_init_raises(self):
        with pytest.raises(RuntimeError, match="not initialised"):
            get_pool()

    @pytest.mark.asyncio()
    async def test_init_creates_pool(self):
        mock_pool = AsyncMock()
        with patch("wp6_data.db.pool.AsyncConnectionPool", return_value=mock_pool):
            result = await init_pool("postgresql://test")
        assert result is mock_pool
        mock_pool.open.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_close_without_init_is_noop(self):
        await close_pool()  # Should not raise

    @pytest.mark.asyncio()
    async def test_close_shuts_down_pool(self):
        mock_pool = AsyncMock()
        with patch("wp6_data.db.pool.AsyncConnectionPool", return_value=mock_pool):
            await init_pool("postgresql://test")
            await close_pool()
        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_get_pool_after_init(self):
        mock_pool = AsyncMock()
        with patch("wp6_data.db.pool.AsyncConnectionPool", return_value=mock_pool):
            await init_pool("postgresql://test")
        assert get_pool() is mock_pool

    @pytest.mark.asyncio()
    async def test_get_pool_after_close_raises(self):
        mock_pool = AsyncMock()
        with patch("wp6_data.db.pool.AsyncConnectionPool", return_value=mock_pool):
            await init_pool("postgresql://test")
            await close_pool()
        with pytest.raises(RuntimeError, match="not initialised"):
            get_pool()
