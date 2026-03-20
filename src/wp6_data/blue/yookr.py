"""Yookr data source — reads from TimescaleDB filtered by project "yookr-direct".

Same interface as deps.py. Delegates to deps query functions with the
project parameter set, so both views share query logic but see different data.
"""

from datetime import datetime
from typing import Any

import pandas as pd

from wp6_data.blue.deps import YOOKR_PROJECT
from wp6_data.blue.deps import fetch_available_sensors as _fetch_available_sensors
from wp6_data.blue.deps import fetch_daily_coverage as _fetch_daily_coverage
from wp6_data.blue.deps import fetch_data as _fetch_data
from wp6_data.blue.deps import fetch_sync_metrics as _fetch_sync_metrics


async def fetch_data(
    sensor_tags: list[str] | None = None,
    device_names: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500000,
) -> pd.DataFrame:
    """Fetch sensor readings from TimescaleDB (yookr-direct project only)."""
    return await _fetch_data(
        sensor_tags=sensor_tags,
        device_names=device_names,
        start=start,
        end=end,
        limit=limit,
        project=YOOKR_PROJECT,
    )


async def fetch_available_sensors() -> list[dict[str, Any]]:
    """Get sensors from TimescaleDB (yookr-direct project only)."""
    return await _fetch_available_sensors(project=YOOKR_PROJECT)


async def fetch_daily_coverage() -> list[dict[str, Any]]:
    """Get daily coverage from TimescaleDB (yookr-direct project only)."""
    return await _fetch_daily_coverage(project=YOOKR_PROJECT)


async def fetch_sync_metrics() -> list[dict[str, Any]]:
    """Get sync metrics for yookr-direct endpoint only."""
    return await _fetch_sync_metrics(project=YOOKR_PROJECT)
