"""Tests for the federated RedSensorProvider.

The provider routes per-sensor between MySQL (legacy LoRaWAN tables) and
the red TimescaleDB (manual measurements + future letsgrow sync) based on
the `source` field on each `sensor_defaults` entry in metadata.yaml.

Tests use the real red metadata registry so routing reflects production.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from wp6_data.red import deps as red_deps
from wp6_data.red.provider import RedSensorProvider
from wp6_data.shared.metadata import MetadataRegistry

RED_YAML = Path(__file__).parent.parent / "src" / "wp6_data" / "red" / "metadata.yaml"


@pytest.fixture()
def red_metadata() -> MetadataRegistry:
    return MetadataRegistry(RED_YAML)


@pytest.fixture()
def mock_mysql(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the global MySQL connection with an AsyncMock."""
    db = AsyncMock()
    monkeypatch.setattr(red_deps, "db", db)
    return db


@pytest.fixture()
def mock_tsdb_fetch_data(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the TSDB fetch_data helper with an AsyncMock."""
    from wp6_data.red import tsdb

    fn = AsyncMock(
        return_value=pd.DataFrame(columns=["device", "sensor", "time", "value"]),
    )
    monkeypatch.setattr(tsdb, "fetch_data_tsdb", fn)
    return fn


@pytest.fixture(autouse=True)
def clear_coverage_cache() -> None:
    """The provider caches coverage for 1h; clear between tests."""
    from wp6_data.red.provider import _coverage_cache

    _coverage_cache.clear()


@pytest.fixture()
def mock_tsdb_coverage(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the TSDB daily-coverage helper with an AsyncMock."""
    from wp6_data.red import tsdb

    fn = AsyncMock(return_value=[])
    monkeypatch.setattr(tsdb, "fetch_daily_coverage_tsdb", fn)
    return fn


@pytest.fixture()
def mock_tsdb_device_counts(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the TSDB per-device count helper with an AsyncMock."""
    from wp6_data.red import tsdb

    fn = AsyncMock(return_value={})
    monkeypatch.setattr(tsdb, "fetch_device_counts_tsdb", fn)
    return fn


def test_init_builds_tsdb_routing_set_from_sensor_defaults_source_field(
    red_metadata: MetadataRegistry,
) -> None:
    """Sensors with non-empty `source` route to TSDB; others to MySQL."""
    provider = RedSensorProvider(metadata=red_metadata)

    # Sijia fruit-chemistry sensors have source: "sijia" → TSDB
    assert "chlorophyll" in provider.tsdb_sensors
    assert "vitamin_c_fresh" in provider.tsdb_sensors

    # Legacy MySQL sensors have no source → MySQL (default)
    assert "par" not in provider.tsdb_sensors
    assert "temp" not in provider.tsdb_sensors
    assert "co2" not in provider.tsdb_sensors


async def test_fetch_data_for_mysql_sensor_only_hits_mysql(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_fetch_data: AsyncMock,
) -> None:
    """A request for a MySQL-routed sensor must not hit TSDB."""
    mock_mysql.get_readings_for_comparison.return_value = pd.DataFrame([
        {
            "device": "s2100-01-par",
            "sensor": "par",
            "time": pd.Timestamp("2025-01-01T12:00:00", tz=UTC),
            "value": 100.0,
        },
    ])
    provider = RedSensorProvider(metadata=red_metadata)

    df = await provider.fetch_data(
        sensor_tags=["par"],
        device_names=["s2100-01-par"],
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
    )

    mock_mysql.get_readings_for_comparison.assert_awaited_once()
    mock_tsdb_fetch_data.assert_not_awaited()
    assert list(df.columns) == ["device", "sensor", "time", "value"]
    assert len(df) == 1


async def test_fetch_data_for_tsdb_sensor_only_hits_tsdb(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_fetch_data: AsyncMock,
) -> None:
    """A request for a TSDB-routed sensor (e.g. chlorophyll) must not hit MySQL."""
    mock_tsdb_fetch_data.return_value = pd.DataFrame([
        {
            "device": "neurath-B-2034-strabelina",
            "sensor": "chlorophyll",
            "time": pd.Timestamp("2025-09-01T00:00:00", tz=UTC),
            "value": 12.3,
        },
    ])
    provider = RedSensorProvider(metadata=red_metadata)

    df = await provider.fetch_data(
        sensor_tags=["chlorophyll"],
        device_names=["neurath-B-2034-strabelina"],
    )

    mock_tsdb_fetch_data.assert_awaited_once()
    mock_mysql.get_readings_for_comparison.assert_not_awaited()
    mock_mysql.get_readings_by_measurement.assert_not_awaited()
    assert list(df.columns) == ["device", "sensor", "time", "value"]
    assert len(df) == 1
    assert df.iloc[0]["sensor"] == "chlorophyll"


async def test_fetch_data_mixed_sources_returns_merged_dataframe(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_fetch_data: AsyncMock,
) -> None:
    """Mixed-source request (e.g. PAR + chlorophyll) returns one merged frame."""
    mock_mysql.get_readings_by_measurement.return_value = pd.DataFrame([
        {
            "device": "s2100-01-par",
            "sensor": "par",
            "time": pd.Timestamp("2025-08-01T12:00:00", tz=UTC),
            "value": 90.0,
        },
    ])
    mock_tsdb_fetch_data.return_value = pd.DataFrame([
        {
            "device": "neurath-B-2034-strabelina",
            "sensor": "chlorophyll",
            "time": pd.Timestamp("2025-09-01T00:00:00", tz=UTC),
            "value": 12.3,
        },
    ])
    provider = RedSensorProvider(metadata=red_metadata)

    df = await provider.fetch_data(sensor_tags=["par", "chlorophyll"])

    mock_mysql.get_readings_by_measurement.assert_awaited_once()
    mock_tsdb_fetch_data.assert_awaited_once()
    assert list(df.columns) == ["device", "sensor", "time", "value"]
    assert set(df["sensor"]) == {"par", "chlorophyll"}
    # Merged frame is sorted by time
    assert list(df["time"]) == sorted(df["time"])


async def test_fetch_available_sensors_includes_tsdb_sensors_from_metadata(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
) -> None:
    """TSDB-side sensors are enumerated from metadata.yaml (no TSDB query).

    Each device with source X yields one entry per sensor_default with the
    same source. Existing MySQL devices/sensors continue to come from the
    legacy MySQL flatten path.
    """
    mock_mysql.get_all_devices.return_value = {
        "s2100-01-par": {
            "tables": ["s2100"], "measurements": ["par"], "readings": 100,
        },
    }
    provider = RedSensorProvider(metadata=red_metadata)

    sensors = await provider.fetch_available_sensors()
    pairs = {(s["device"], s["sensor"]) for s in sensors}

    # MySQL device pairs survive
    assert ("s2100-01-par", "par") in pairs

    # Each Sijia device is paired with every Sijia sensor_default
    sijia_sensors = {
        tag for tag, m in red_metadata.sensor_defaults.items() if m.source == "sijia"
    }
    for device in ("neurath-B-2034-strabelina", "neurath-B-2012-shivious"):
        for sensor in sijia_sensors:
            assert (device, sensor) in pairs


async def test_fetch_device_data_includes_tsdb_devices_from_metadata(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_device_counts: AsyncMock,
) -> None:
    """fetch_device_data merges MySQL devices with TSDB-declared devices."""
    mock_mysql.get_all_devices.return_value = {
        "s2100-01-par": {
            "tables": ["s2100"], "measurements": ["par"], "readings": 100,
        },
    }
    provider = RedSensorProvider(metadata=red_metadata)

    devices = await provider.fetch_device_data()

    assert "s2100-01-par" in devices
    assert "par" in devices["s2100-01-par"]["sensors"]

    # Sijia devices appear with all Sijia sensors declared in metadata
    sijia_sensors = {
        tag for tag, m in red_metadata.sensor_defaults.items() if m.source == "sijia"
    }
    assert "neurath-B-2034-strabelina" in devices
    assert set(devices["neurath-B-2034-strabelina"]["sensors"]) == sijia_sensors


async def test_fetch_device_data_populates_tsdb_reading_counts(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_device_counts: AsyncMock,
) -> None:
    """TSDB-backed devices show actual row counts from the readings table."""
    mock_mysql.get_all_devices.return_value = {}
    mock_tsdb_device_counts.return_value = {
        "neurath-B-2034-strabelina": {"readings": 42, "last_seen": None},
        "neurath-B-2012-shivious": {"readings": 17, "last_seen": None},
    }
    provider = RedSensorProvider(metadata=red_metadata)

    devices = await provider.fetch_device_data()

    assert devices["neurath-B-2034-strabelina"]["readings"] == 42
    assert devices["neurath-B-2012-shivious"]["readings"] == 17


async def test_fetch_device_data_zero_count_for_tsdb_device_with_no_rows(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_device_counts: AsyncMock,
) -> None:
    """A TSDB device with no readings yet still appears, with count 0."""
    mock_mysql.get_all_devices.return_value = {}
    mock_tsdb_device_counts.return_value = {}  # no rows in DB at all
    provider = RedSensorProvider(metadata=red_metadata)

    devices = await provider.fetch_device_data()

    # Devices declared in metadata still appear (structural enumeration)
    assert "neurath-B-2034-strabelina" in devices
    assert devices["neurath-B-2034-strabelina"]["readings"] == 0


async def test_fetch_daily_coverage_merges_mysql_and_tsdb(
    red_metadata: MetadataRegistry,
    mock_mysql: AsyncMock,
    mock_tsdb_coverage: AsyncMock,
) -> None:
    """Coverage must include rows from both backends.

    Coverage is the one method that legitimately queries the data store
    (metadata has no per-day info). The merge is structural.
    """
    from datetime import date

    # Stub MySQL cursor path — fetch_daily_coverage iterates SENSOR_TABLES.
    cursor = AsyncMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[("s2100-01-par", date(2025, 1, 1))])
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
    mock_mysql.pool = pool

    mock_tsdb_coverage.return_value = [
        {"device": "neurath-B-2034-strabelina",
         "sensor": "chlorophyll", "day": date(2025, 9, 1)},
    ]

    provider = RedSensorProvider(metadata=red_metadata)
    coverage = await provider.fetch_daily_coverage()

    pairs = {(c["device"], c["sensor"], c["day"]) for c in coverage}
    assert ("s2100-01-par", "par", date(2025, 1, 1)) in pairs
    assert (
        "neurath-B-2034-strabelina", "chlorophyll", date(2025, 9, 1),
    ) in pairs
    mock_tsdb_coverage.assert_awaited_once()
