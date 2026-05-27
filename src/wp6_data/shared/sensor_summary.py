"""Shared sensor summary with TTL caching.

Both blue and red dashboards use this to avoid re-querying sensor metadata
on every page load. Each twin provides its own async fetcher; this module
handles the caching and exposes a common interface.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from cachetools import TTLCache

# Async function that returns a list of sensor summary dicts
Fetcher = Callable[..., Awaitable[list[dict[str, Any]]]]

# Single shared cache: keyed by (twin, project/source) identifiers
_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=32, ttl=300)


async def get_sensor_summary(
    key: str,
    fetcher: Fetcher,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Return cached sensor summary, calling *fetcher* on cache miss.

    Args:
        key: Cache key, e.g. "blue" or "blue:yookr-direct" or "red".
        fetcher: Async callable that returns the raw sensor list.
        **kwargs: Forwarded to *fetcher* on cache miss.
    """
    if key in _cache:
        return _cache[key]
    result = await fetcher(**kwargs)
    _cache[key] = result
    return result


def invalidate(key: str | None = None) -> None:
    """Drop one or all cached sensor summaries."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


