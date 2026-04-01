"""Blue sensor data provider — satisfies SensorDataProvider protocol.

Wraps the existing deps/yookr module-level functions and internalises
the cookie-based data-source dispatch from datasource.py.
"""

from __future__ import annotations

from datetime import datetime
from types import ModuleType
from typing import Any

import pandas as pd

from wp6_data.blue import deps, yookr
from wp6_data.config import Settings

SOURCES: dict[str, ModuleType] = {
    "spohf-datalake": deps,
    "yookr": yookr,
}

SOURCE_LABELS: dict[str, str] = {
    "spohf-datalake": "SPoHF Datalake",
    "yookr": "Yookr API",
}

_default_source = Settings().blue_default_source


class BlueSensorProvider:
    """SensorDataProvider backed by TimescaleDB with multi-source dispatch."""

    def __init__(self, source_name: str | None = None) -> None:
        self._source_name = (
            source_name if source_name in SOURCES else _default_source
        )
        self._source: ModuleType = SOURCES[self._source_name]

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def data_source_label(self) -> str | None:
        return self._source_name

    async def fetch_data(
        self,
        sensor_tags: list[str] | None = None,
        device_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500_000,
    ) -> pd.DataFrame:
        return await self._source.fetch_data(
            sensor_tags=sensor_tags,
            device_names=device_names,
            start=start,
            end=end,
            limit=limit,
        )

    async def fetch_available_sensors(self) -> list[dict[str, Any]]:
        return await self._source.fetch_available_sensors()

    async def fetch_device_data(self) -> dict[str, dict]:
        sensors = await self.fetch_available_sensors()
        device_data: dict[str, dict] = {}
        for s in sensors:
            info = device_data.setdefault(
                s["device"], {"sensors": set(), "readings": 0},
            )
            info["sensors"].add(s["sensor"])
            info["readings"] += s["readings"]
        for info in device_data.values():
            info["sensors"] = list(info["sensors"])
        return device_data

    def show_exports(self) -> bool:
        """Whether CSV exports are relevant for the active source."""
        return self._source_name == "spohf-datalake"
