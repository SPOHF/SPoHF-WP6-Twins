"""Blue sensor data provider — satisfies SensorDataProvider protocol.

Wraps the blue deps module functions. The SPoHF datalake is blue's only
automated source, so there is nothing to filter on: one provider instance.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from wp6_data.blue import deps


class BlueSensorProvider:
    """SensorDataProvider backed by TimescaleDB."""

    def __init__(self, *, source_key: str | None = None) -> None:
        self._source_key = source_key

    @property
    def data_source_label(self) -> str | None:
        return self._source_key

    async def fetch_data(
        self,
        sensor_tags: list[str] | None = None,
        device_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500_000,
        *,
        bucket: timedelta | None = None,
        agg: str | None = None,
    ) -> pd.DataFrame:
        return await deps.fetch_data(
            sensor_tags=sensor_tags,
            device_names=device_names,
            start=start,
            end=end,
            limit=limit,
            bucket=bucket,
            agg=agg,
        )

    async def fetch_available_sensors(self) -> list[dict[str, Any]]:
        return await deps.fetch_available_sensors()

    async def fetch_sync_metrics(self) -> list[dict[str, Any]]:
        return await deps.fetch_sync_metrics()

    async def fetch_daily_coverage(self) -> list[dict[str, Any]]:
        return await deps.fetch_daily_coverage()

    async def fetch_device_data(self) -> dict[str, dict]:
        sensors = await self.fetch_available_sensors()
        device_data: dict[str, dict] = {}
        for s in sensors:
            info = device_data.setdefault(
                s["device"],
                {"sensors": set(), "readings": 0, "last_seen": None},
            )
            info["sensors"].add(s["sensor"])
            info["readings"] += s["readings"]
        for info in device_data.values():
            info["sensors"] = list(info["sensors"])
        return device_data

    async def fetch_manual_metadata(self) -> dict[str, Any]:
        """Manual-upload freshness for the blue home page.

        Delegates to the shared twin-agnostic manual-upload summary query.
        Returns empty dicts until the first manual upload is applied.
        """
        from wp6_data.db.pool import get_pool
        from wp6_data.db.queries import fetch_manual_summary

        return await fetch_manual_summary(get_pool())
