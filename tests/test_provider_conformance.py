"""Protocol-conformance suite for the twin SensorDataProviders.

One parametrized suite asserting the SensorDataProvider contract (see the
docstrings in ``wp6_data.shared.twin``) uniformly across the three adapters:

- grey: the real in-memory GreySensorProvider (no mocking needed),
- blue: BlueSensorProvider over monkeypatched ``wp6_data.blue.deps`` functions,
- red:  RedSensorProvider over an AsyncMock MySQL connection and patched
  ``wp6_data.red.tsdb`` helpers (same approach as tests/test_red_provider.py).

Deliberately protocol-shape assertions only — per-provider behaviour (routing,
merging, caching) lives in the provider-specific test modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from wp6_data.shared.twin import SensorDataProvider

# The documented raw-path fetch_data shape (shared/twin.py fetch_data docstring).
RAW_COLUMNS = ["device", "sensor", "time", "value"]

# The documented fetch_manual_metadata shape.
MANUAL_METADATA_KEYS = {"uploads", "measurements"}

RED_YAML = Path(__file__).parent.parent / "src" / "wp6_data" / "red" / "metadata.yaml"

# A sensor tag no twin declares — used to force the empty fetch_data path.
MISSING_SENSOR = "no-such-sensor"


@dataclass
class Expectations:
    """Per-provider call recipes for exercising both fetch_data paths."""

    nonempty_fetch_kwargs: dict[str, Any] = field(default_factory=dict)
    empty_fetch_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"sensor_tags": [MISSING_SENSOR]},
    )


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "device": "dev-1",
            "sensor": "temp",
            "time": pd.Timestamp("2026-01-01T12:00:00", tz=UTC),
            "value": 21.5,
        },
    ])


@pytest.fixture(autouse=True)
def _clear_red_caches():
    """Red's TTL caches (cagg summary, coverage) must not leak across tests."""
    from wp6_data.red.provider import _coverage_cache
    from wp6_data.shared import sensor_summary

    _coverage_cache.clear()
    sensor_summary.invalidate()
    yield
    _coverage_cache.clear()
    sensor_summary.invalidate()


@pytest.fixture()
def grey_case() -> tuple[SensorDataProvider, Expectations]:
    from wp6_data.grey.provider import GreySensorProvider

    return GreySensorProvider(), Expectations()


@pytest.fixture()
def blue_case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SensorDataProvider, Expectations]:
    from wp6_data.blue import deps as blue_deps
    from wp6_data.blue.provider import BlueSensorProvider
    from wp6_data.db import pool as db_pool
    from wp6_data.db import queries as db_queries

    async def fake_fetch_data(sensor_tags=None, **_kwargs):
        if sensor_tags == [MISSING_SENSOR]:
            return pd.DataFrame(columns=RAW_COLUMNS)
        return _raw_frame()

    monkeypatch.setattr(blue_deps, "fetch_data", fake_fetch_data)
    monkeypatch.setattr(
        blue_deps,
        "fetch_available_sensors",
        AsyncMock(return_value=[
            {"device": "dev-1", "sensor": "temp", "readings": 5},
            {"device": "dev-1", "sensor": "hum", "readings": 3},
        ]),
    )
    monkeypatch.setattr(blue_deps, "fetch_sync_metrics", AsyncMock(return_value=[]))
    monkeypatch.setattr(blue_deps, "fetch_daily_coverage", AsyncMock(return_value=[]))
    # fetch_manual_metadata imports these lazily inside the method.
    monkeypatch.setattr(db_pool, "get_pool", lambda: object())
    monkeypatch.setattr(
        db_queries,
        "fetch_manual_summary",
        AsyncMock(return_value={"uploads": {}, "measurements": {}}),
    )

    provider = BlueSensorProvider()
    return provider, Expectations()


def _mysql_pool_stub(rows: list) -> AsyncMock:
    """Async-context pool/cursor stub for the coverage query path."""
    cursor = AsyncMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    cursor_ctx = AsyncMock()
    cursor_ctx.__aenter__ = AsyncMock(return_value=cursor)
    cursor_ctx.__aexit__ = AsyncMock(return_value=False)
    conn = AsyncMock()
    conn.cursor = lambda: cursor_ctx
    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = AsyncMock()
    pool.acquire = lambda: conn_ctx
    return pool


@pytest.fixture()
def red_case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SensorDataProvider, Expectations]:
    from wp6_data.red import deps as red_deps
    from wp6_data.red import tsdb
    from wp6_data.red.provider import RedSensorProvider
    from wp6_data.shared.metadata import MetadataRegistry

    db = AsyncMock()
    db.get_all_devices.return_value = {
        "s2100-01-par": {
            "tables": ["s2100"], "measurements": ["par"],
            "readings": 100, "last_seen": None,
        },
    }
    db.get_wire_device_summary.return_value = {}
    db.get_readings_by_measurement.return_value = pd.DataFrame([
        {
            "device": "s2100-01-par",
            "sensor": "par",
            "time": pd.Timestamp("2026-01-01T12:00:00", tz=UTC),
            "value": 90.0,
        },
    ])
    db.pool = _mysql_pool_stub(rows=[])
    monkeypatch.setattr(red_deps, "db", db)

    monkeypatch.setattr(
        tsdb, "fetch_data_tsdb",
        AsyncMock(return_value=pd.DataFrame(columns=RAW_COLUMNS)),
    )
    monkeypatch.setattr(tsdb, "fetch_sensors_from_cagg", AsyncMock(return_value=[]))
    monkeypatch.setattr(tsdb, "fetch_sync_metrics_tsdb", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        tsdb, "fetch_daily_coverage_from_table", AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        tsdb,
        "fetch_manual_summary_tsdb",
        AsyncMock(return_value={"uploads": {}, "measurements": {}}),
    )

    provider = RedSensorProvider(metadata=MetadataRegistry(RED_YAML))
    return provider, Expectations(
        # "par" routes to the (mocked) MySQL leg of the federated provider.
        nonempty_fetch_kwargs={"sensor_tags": ["par"]},
        # No filters at all → structurally empty result on the raw path.
        empty_fetch_kwargs={},
    )


@pytest.fixture(params=["grey", "blue", "red"])
def case(request: pytest.FixtureRequest) -> tuple[SensorDataProvider, Expectations]:
    return request.getfixturevalue(f"{request.param}_case")


def test_satisfies_runtime_checkable_protocol(case) -> None:
    provider, _ = case
    assert isinstance(provider, SensorDataProvider)


async def test_fetch_data_nonempty_raw_path_has_exact_columns(case) -> None:
    provider, exp = case
    df = await provider.fetch_data(**exp.nonempty_fetch_kwargs)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert list(df.columns) == RAW_COLUMNS  # raw path: no count column


async def test_fetch_data_empty_raw_path_keeps_contract_columns(case) -> None:
    provider, exp = case
    df = await provider.fetch_data(**exp.empty_fetch_kwargs)
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == RAW_COLUMNS


async def test_fetch_available_sensors_rows_carry_required_keys(case) -> None:
    provider, _ = case
    sensors = await provider.fetch_available_sensors()
    assert isinstance(sensors, list)
    assert sensors
    for row in sensors:
        assert isinstance(row, dict)
        assert {"device", "sensor", "readings"} <= row.keys()


async def test_fetch_device_data_values_carry_sensors_and_readings(case) -> None:
    provider, _ = case
    devices = await provider.fetch_device_data()
    assert isinstance(devices, dict)
    assert devices
    for device_id, info in devices.items():
        assert isinstance(device_id, str)
        assert isinstance(info, dict)
        assert isinstance(info["sensors"], list)
        assert isinstance(info["readings"], int)
        assert "last_seen" in info


async def test_sync_metrics_and_daily_coverage_return_lists(case) -> None:
    provider, _ = case
    assert isinstance(await provider.fetch_sync_metrics(), list)
    assert isinstance(await provider.fetch_daily_coverage(), list)


async def test_fetch_manual_metadata_has_uploads_and_measurements_dicts(case) -> None:
    provider, _ = case
    meta = await provider.fetch_manual_metadata()
    assert isinstance(meta, dict)
    assert meta.keys() >= MANUAL_METADATA_KEYS
    for key in MANUAL_METADATA_KEYS:
        assert isinstance(meta[key], dict)


