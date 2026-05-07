"""Red sensor data provider — federated over MySQL and red TimescaleDB.

Routes per-sensor based on the `source` field on `sensor_defaults` entries
in the red MetadataRegistry. Sensors with no source go to MySQL (the
legacy LoRaWAN tables); sensors with a source go to TimescaleDB (manual
uploads + future letsgrow sync). The routing map is built once at init.
Federation is transparent — public protocol surface is unchanged.

Red-specific methods (get_par_readings, get_weather_station_readings)
stay on MySQLConnection and are accessed directly by DLI routes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
from cachetools import TTLCache

# Coverage only changes once per day — cache for 1 hour
_coverage_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=4, ttl=3600)

if TYPE_CHECKING:
    from wp6_data.red.db import MySQLConnection
    from wp6_data.shared.metadata import MetadataRegistry


class RedSensorProvider:
    """Federated SensorDataProvider over MySQL and red TimescaleDB.

    Lazily references deps.db so the provider can be created before
    the MySQL connection is established at startup.
    """

    def __init__(self, metadata: MetadataRegistry) -> None:
        self._metadata = metadata
        self.tsdb_sensors: frozenset[str] = frozenset(
            tag for tag, meta in metadata.sensor_defaults.items() if meta.source
        )

    @property
    def db(self) -> MySQLConnection:
        """Direct access to the underlying MySQL connection for DLI routes."""
        from wp6_data.red import deps

        if deps.db is None:
            raise RuntimeError("Database not connected")
        return deps.db

    @property
    def data_source_label(self) -> str | None:
        return None

    async def fetch_sync_metrics(self) -> list[dict[str, Any]]:
        return []

    async def fetch_daily_coverage(self) -> list[dict[str, Any]]:
        """Derive daily coverage from MySQL sensor tables (cached 1 hour)."""
        key = "red:coverage"
        if key in _coverage_cache:
            return _coverage_cache[key]
        result = await self._fetch_daily_coverage()
        _coverage_cache[key] = result
        return result

    async def _fetch_daily_coverage(self) -> list[dict[str, Any]]:
        """Distinct (device, sensor, day) triples — MySQL + TSDB merged."""
        from wp6_data.red.db import SENSOR_TABLES
        from wp6_data.red.tsdb import fetch_daily_coverage_tsdb

        records: list[dict[str, Any]] = []
        async with self.db.pool.acquire() as conn, conn.cursor() as cursor:
            for table, measurements in SENSOR_TABLES.items():
                try:
                    await cursor.execute(
                        f"SELECT DISTINCT device_id, DATE(received_at) AS day "
                        f"FROM {table}",
                    )
                    rows = await cursor.fetchall()
                except Exception:
                    continue
                for device_id, day in rows:
                    for sensor in measurements:
                        records.append({
                            "device": device_id,
                            "sensor": sensor,
                            "day": day,
                        })

        records.extend(await fetch_daily_coverage_tsdb())
        return records

    def _split_by_route(
        self, sensor_tags: list[str] | None,
    ) -> tuple[list[str], list[str]]:
        """Partition sensor_tags into (mysql_tags, tsdb_tags)."""
        if not sensor_tags:
            return [], []
        mysql_tags = [t for t in sensor_tags if t not in self.tsdb_sensors]
        tsdb_tags = [t for t in sensor_tags if t in self.tsdb_sensors]
        return mysql_tags, tsdb_tags

    async def _fetch_mysql(
        self,
        sensor_tags: list[str],
        device_names: list[str] | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> pd.DataFrame:
        """MySQL leg of fetch_data — preserves the existing shape contract."""
        device = device_names[0] if device_names else None
        sensor = sensor_tags[0] if sensor_tags else None
        if device and sensor:
            return await self.db.get_readings_for_comparison(
                device, sensor, start=start, end=end, limit=limit,
            )
        if sensor:
            return await self.db.get_readings_by_measurement(
                sensor, start=start, end=end, limit_per_table=limit,
            )
        return pd.DataFrame(columns=["device", "sensor", "time", "value"])

    async def fetch_data(
        self,
        sensor_tags: list[str] | None = None,
        device_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500_000,
    ) -> pd.DataFrame:
        """Fetch readings, dispatching per-sensor between MySQL and TSDB."""
        from wp6_data.red.tsdb import fetch_data_tsdb

        mysql_tags, tsdb_tags = self._split_by_route(sensor_tags)
        frames: list[pd.DataFrame] = []
        if mysql_tags:
            frames.append(await self._fetch_mysql(
                mysql_tags, device_names, start, end, limit,
            ))
        if tsdb_tags:
            frames.append(await fetch_data_tsdb(
                sensor_tags=tsdb_tags,
                device_names=device_names,
                start=start, end=end, limit=limit,
            ))
        if not frames:
            return pd.DataFrame(columns=["device", "sensor", "time", "value"])
        if len(frames) == 1:
            return frames[0]
        merged = pd.concat(frames, ignore_index=True)
        if not merged.empty:
            merged = merged.sort_values("time").reset_index(drop=True)
        return merged

    def _tsdb_devices_by_source(self) -> dict[str, list[str]]:
        """Group TSDB-routed devices by their `source` value.

        Maps source → [device_id, ...]. Only devices with a non-empty
        `source` are TSDB-backed; the rest are MySQL.
        """
        grouped: dict[str, list[str]] = {}
        for device_id, dev in self._metadata.devices.items():
            if dev.source:
                grouped.setdefault(dev.source, []).append(device_id)
        return grouped

    def _enumerate_tsdb_sensors(self) -> list[tuple[str, str]]:
        """List (device, sensor) pairs declared in metadata for TSDB sources."""
        sensors_by_source: dict[str, list[str]] = {}
        for tag, meta in self._metadata.sensor_defaults.items():
            if meta.source:
                sensors_by_source.setdefault(meta.source, []).append(tag)

        pairs: list[tuple[str, str]] = []
        for source, devices in self._tsdb_devices_by_source().items():
            for device in devices:
                for sensor in sensors_by_source.get(source, []):
                    pairs.append((device, sensor))
        return pairs

    async def fetch_available_sensors(self) -> list[dict[str, Any]]:
        """Flat [{device, sensor, readings}, ...] across both backends.

        - MySQL: derived from get_all_devices() (existing behaviour).
        - TSDB: derived structurally from metadata.yaml — every device with
          source X is paired with every sensor_default having source X.
          Reading counts are 0 because metadata has no time/count info.
        """
        all_devices = await self.db.get_all_devices()
        result: list[dict[str, Any]] = []
        for device_id, info in sorted(all_devices.items()):
            for measurement in sorted(info["measurements"]):
                result.append({
                    "device": device_id,
                    "sensor": measurement,
                    "readings": info["readings"],
                })

        for device, sensor in self._enumerate_tsdb_sensors():
            result.append({"device": device, "sensor": sensor, "readings": 0})
        return result

    async def fetch_device_data(self) -> dict[str, dict]:
        """Device overview for the home page (MySQL + TSDB merged)."""
        all_devices = await self.db.get_all_devices()

        device_data: dict[str, dict] = {}
        for device_id, info in all_devices.items():
            device_data[device_id] = {
                "sensors": info["measurements"],
                "readings": info["readings"],
            }

        for device, sensor in self._enumerate_tsdb_sensors():
            entry = device_data.setdefault(
                device, {"sensors": [], "readings": 0},
            )
            if sensor not in entry["sensors"]:
                entry["sensors"].append(sensor)
        return device_data
