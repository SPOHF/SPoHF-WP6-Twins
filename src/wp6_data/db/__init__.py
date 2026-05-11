"""Shared TimescaleDB integration (pool, schema helpers, queries).

Used by both blue and red twins. Each twin opens its own pool against its own
database; this package provides the pool/query/schema helpers without
encoding twin-specific knowledge.
"""

from wp6_data.db.pool import close_pool, get_pool, init_pool
from wp6_data.db.queries import (
    rebuild_daily_coverage,
    record_sync_run,
    refresh_sensor_summary,
    refresh_sensor_summary_recent,
    upsert_daily_coverage,
    upsert_readings,
)
from wp6_data.db.schema import ensure_aggregates, ensure_schema

__all__ = [
    "close_pool",
    "ensure_aggregates",
    "ensure_schema",
    "get_pool",
    "init_pool",
    "rebuild_daily_coverage",
    "record_sync_run",
    "refresh_sensor_summary",
    "refresh_sensor_summary_recent",
    "upsert_daily_coverage",
    "upsert_readings",
]
