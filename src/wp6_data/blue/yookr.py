"""Yookr data source — reads from Neo4j filtered by project "yookr-direct".

Same interface as deps.py. Delegates to deps query functions with the
project parameter set, so both views share query logic but see different data.
"""

from datetime import datetime
from typing import Any

import pandas as pd

from wp6_data.blue.deps import (
    YOOKR_PROJECT,
    fetch_sync_metrics,  # noqa: F401 — re-exported as-is
)
from wp6_data.blue.deps import fetch_available_sensors as _fetch_available_sensors
from wp6_data.blue.deps import fetch_daily_coverage as _fetch_daily_coverage
from wp6_data.blue.deps import fetch_data as _fetch_data


def fetch_data(
    sensor_tags: list[str] | None = None,
    device_names: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50000,
) -> pd.DataFrame:
    """Fetch sensor readings from Neo4j (yookr-direct project only)."""
    return _fetch_data(
        sensor_tags=sensor_tags,
        device_names=device_names,
        start=start,
        end=end,
        limit=limit,
        project=YOOKR_PROJECT,
    )


def fetch_available_sensors() -> list[dict[str, Any]]:
    """Get sensors from Neo4j (yookr-direct project only)."""
    return _fetch_available_sensors(project=YOOKR_PROJECT)


def fetch_daily_coverage() -> list[dict[str, Any]]:
    """Get daily coverage from Neo4j (yookr-direct project only)."""
    return _fetch_daily_coverage(project=YOOKR_PROJECT)
