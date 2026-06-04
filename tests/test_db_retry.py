"""Tests for the red MySQL connection-lost retry decorator."""

from __future__ import annotations

import pytest
from pymysql.err import OperationalError

from wp6_data.red.db import _retry_on_disconnect


async def test_retries_then_succeeds():
    calls = {"n": 0}

    @_retry_on_disconnect(retries=2, delay=0)
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise OperationalError(2013, "Lost connection")
        return "ok"

    assert await flaky() == "ok"
    assert calls["n"] == 2  # failed once, succeeded on retry


async def test_gives_up_after_max_retries():
    calls = {"n": 0}

    @_retry_on_disconnect(retries=1, delay=0)
    async def always_lost():
        calls["n"] += 1
        raise OperationalError(2006, "MySQL server has gone away")

    with pytest.raises(OperationalError):
        await always_lost()
    assert calls["n"] == 2  # initial try + one retry


async def test_non_retryable_error_raises_immediately():
    calls = {"n": 0}

    @_retry_on_disconnect(retries=3, delay=0)
    async def bad_sql():
        calls["n"] += 1
        raise OperationalError(1064, "You have an error in your SQL syntax")

    with pytest.raises(OperationalError):
        await bad_sql()
    assert calls["n"] == 1  # not retried
