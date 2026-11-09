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
    # check= pings each connection on checkout, so one killed by a server
    # restart is replaced instead of failing the request it was handed to.
    _pool = AsyncConnectionPool(
        dsn, min_size=min_size, max_size=max_size, open=False,
        check=AsyncConnectionPool.check_connection,
    )
    await _pool.open()
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
