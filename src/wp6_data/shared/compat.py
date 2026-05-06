"""Cross-platform asyncio compatibility helpers."""

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run *coro* in a new event loop, using SelectorEventLoop on Windows.

    psycopg3 (and aiomysql) use ``add_reader()`` internally, which is not
    supported by the default ``ProactorEventLoop`` on Windows (Python 3.8+).
    This wrapper transparently switches to ``SelectorEventLoop`` on Windows;
    on all other platforms it delegates straight to ``asyncio.run()``.
    """
    if sys.platform == "win32":
        import selectors

        return asyncio.run(
            coro,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(coro)
