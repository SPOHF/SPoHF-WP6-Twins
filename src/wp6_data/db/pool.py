"""Async connection pool for TimescaleDB via psycopg."""

import structlog
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

_pool: AsyncConnectionPool | None = None


async def init_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> AsyncConnectionPool:
    """Create and open the global async connection pool."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = AsyncConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={"connect_timeout": 5},
    )
    # wait=False: don't block startup if DB is unreachable; connections are
    # created lazily on first use (pool.connection() timeout guards each call).
    await _pool.open(wait=False)
    logger.info("tsdb_pool_opened", min_size=min_size, max_size=max_size)
    return _pool


def get_pool() -> AsyncConnectionPool:
    """Return the global pool. Raises if not initialised."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialised — call init_pool() first")
    return _pool


async def close_pool() -> None:
    """Close the global pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("tsdb_pool_closed")
