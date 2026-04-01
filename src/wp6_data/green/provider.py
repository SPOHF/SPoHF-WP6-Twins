"""Green sensor data provider — in-memory demo data.

Generates synthetic sensor readings so the green twin can run without
any database. Useful as a POC and as a template for new twins.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

# Demo sensor definitions: (device, sensor, base_value, amplitude)
_SENSORS = [
    ("herb-box-01", "temp", 22.0, 3.0),
    ("herb-box-01", "hum", 55.0, 15.0),
    ("herb-box-01", "soil_moisture", 40.0, 10.0),
    ("herb-box-01", "light", 5000.0, 4000.0),
    ("herb-box-02", "temp", 21.0, 2.5),
    ("herb-box-02", "hum", 60.0, 12.0),
    ("herb-box-02", "soil_moisture", 45.0, 8.0),
    ("outdoor-station", "temp", 15.0, 8.0),
    ("outdoor-station", "hum", 65.0, 20.0),
    ("outdoor-station", "light", 20000.0, 18000.0),
]

READING_INTERVAL = timedelta(minutes=10)
DEFAULT_DAYS = 7


def _generate_readings(
    device: str,
    sensor: str,
    base: float,
    amplitude: float,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Generate sine-wave readings with slight noise."""
    records = []
    t = start
    period_hours = 24.0
    while t <= end:
        hours = (t - start).total_seconds() / 3600
        # Daily sine wave + small jitter
        value = base + amplitude * math.sin(2 * math.pi * hours / period_hours)
        # Add a bit of "noise" via a faster oscillation
        value += amplitude * 0.05 * math.sin(2 * math.pi * hours / 1.7)
        records.append({
            "device": device,
            "sensor": sensor,
            "time": t,
            "value": round(value, 2),
        })
        t += READING_INTERVAL
    return records


class GreenSensorProvider:
    """SensorDataProvider backed by in-memory generated data."""

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
        now = datetime.now(tz=UTC)
        if end is None:
            end = now
        if start is None:
            start = end - timedelta(days=DEFAULT_DAYS)

        records: list[dict[str, Any]] = []
        for device, sensor, base, amp in _SENSORS:
            if sensor_tags and sensor not in sensor_tags:
                continue
            if device_names and device not in device_names:
                continue
            records.extend(_generate_readings(device, sensor, base, amp, start, end))

        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("time").head(limit)
        return df

    async def fetch_available_sensors(self) -> list[dict[str, Any]]:
        return [
            {"device": device, "sensor": sensor, "readings": 1008}
            for device, sensor, _, _ in _SENSORS
        ]

    async def fetch_device_data(self) -> dict[str, dict]:
        devices: dict[str, dict] = {}
        for device, sensor, _, _ in _SENSORS:
            info = devices.setdefault(device, {"sensors": [], "readings": 1008})
            info["sensors"].append(sensor)
        return devices
