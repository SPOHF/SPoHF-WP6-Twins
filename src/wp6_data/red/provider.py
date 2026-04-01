"""Red sensor data provider — satisfies SensorDataProvider protocol.

Thin wrapper around MySQLConnection, normalising the multi-table schema
into the unified (device, sensor, time, value) shape.  Red-specific
methods (get_par_readings, get_weather_station_readings) stay on
MySQLConnection and are accessed directly by DLI routes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from wp6_data.red.db import MySQLConnection


class RedSensorProvider:
    """SensorDataProvider backed by MySQL with per-table sensor schema.

    Lazily references deps.db so the provider can be created before
    the database connection is established at startup.
    """

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

    async def fetch_data(
        self,
        sensor_tags: list[str] | None = None,
        device_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500_000,
    ) -> pd.DataFrame:
        """Fetch readings for a single device+sensor combo.

        The shared API route calls this with exactly one device and one sensor,
        which maps to MySQLConnection.get_readings_for_comparison().
        """
        device = device_names[0] if device_names else None
        sensor = sensor_tags[0] if sensor_tags else None

        if device and sensor:
            return await self.db.get_readings_for_comparison(
                device, sensor, start=start, end=end, limit=limit,
            )

        # Fallback: if only sensor given, use cross-table measurement query
        if sensor:
            return await self.db.get_readings_by_measurement(
                sensor, start=start, end=end, limit_per_table=limit,
            )

        return pd.DataFrame(columns=["device", "sensor", "time", "value"])

    async def fetch_available_sensors(self) -> list[dict[str, Any]]:
        """Normalise red's device-centric model to [{device, sensor, readings}].

        Red's get_all_devices() returns {device_id: {tables, measurements}}.
        Red's get_available_sensors() returns [{table, devices, readings, measurements}].
        We combine them into the blue-style flat list.
        """
        all_devices = await self.db.get_all_devices()
        table_info = await self.db.get_available_sensors()

        # Build lookup: table → {readings, device_count}
        table_readings: dict[str, int] = {}
        table_device_count: dict[str, int] = {}
        for s in table_info:
            table_readings[s["table"]] = s["readings"]
            table_device_count[s["table"]] = s["devices"]

        result: list[dict[str, Any]] = []
        for device_id, info in sorted(all_devices.items()):
            # Estimate per-device readings from table totals
            total = sum(
                table_readings.get(t, 0) // max(table_device_count.get(t, 1), 1)
                for t in info["tables"]
            )
            for measurement in sorted(info["measurements"]):
                result.append({
                    "device": device_id,
                    "sensor": measurement,
                    "readings": total,
                })
        return result

    async def fetch_device_data(self) -> dict[str, dict]:
        """Device overview for the home page."""
        all_devices = await self.db.get_all_devices()
        table_info = await self.db.get_available_sensors()

        table_readings: dict[str, int] = {}
        table_device_count: dict[str, int] = {}
        for s in table_info:
            table_readings[s["table"]] = s["readings"]
            table_device_count[s["table"]] = s["devices"]

        device_data: dict[str, dict] = {}
        for device_id, info in all_devices.items():
            total = sum(
                table_readings.get(t, 0) // max(table_device_count.get(t, 1), 1)
                for t in info["tables"]
            )
            device_data[device_id] = {
                "sensors": info["measurements"],
                "readings": total,
            }
        return device_data
