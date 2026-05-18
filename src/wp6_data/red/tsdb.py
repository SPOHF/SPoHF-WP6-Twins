"""TimescaleDB schema bootstrap and read helpers for the red twin.

Red's `readings` has a different column shape than blue's: a `source` column
(mutually exclusive data origins — manual / Neurath / legacy — see
``project_blue_project_vs_red_source`` memo, not a rename of blue's `project`)
plus a nullable `upload_id` FK to `manual_uploads` for rows that came from a
manual Excel upload.

The cagg + `sync_metadata` + `daily_coverage` infrastructure is twin-agnostic
and lives in `wp6_data.db.schema`/`queries`; `ensure_schema_red` delegates to
`ensure_aggregates(pool, project_column="source")` after creating red's
readings hypertable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from wp6_data.db.queries import rebuild_daily_coverage
from wp6_data.db.schema import MANUAL_UPLOADS_SQL, ensure_aggregates

logger = structlog.get_logger()

# `manual_uploads` is now the shared, twin-agnostic constant; red's readings
# DDL (with its `source` column + `upload_id` FK + source-aware dedup index)
# stays red-owned. Composed so the emitted bootstrap SQL is unchanged.
_READINGS_RED_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    time        TIMESTAMPTZ      NOT NULL,
    device_name TEXT             NOT NULL,
    sensor_tag  TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    raw_value   TEXT,
    source      TEXT             NOT NULL DEFAULT 'unknown',
    synced_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    upload_id   BIGINT           REFERENCES manual_uploads(id)
);

SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_readings_device_tag
    ON readings (device_name, sensor_tag, time DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup
    ON readings (source, device_name, sensor_tag, time);
"""

# Shared audit table + red readings DDL. Concatenation preserves the exact
# statement set red bootstrapped before promotion.
SCHEMA_SQL = MANUAL_UPLOADS_SQL + _READINGS_RED_SQL


async def ensure_schema_red(pool: AsyncConnectionPool) -> None:
    """Bootstrap red's TSDB schema and aggregates idempotently.

    Order matters: readings hypertable first, then the shared aggregates
    helper which creates `sync_metadata`, `daily_coverage`, and the
    `sensors_daily_summary` continuous aggregate (with a background refresh
    policy installed by `ensure_aggregates`). On first run after data already
    exists (e.g. historical Sijia uploads), a one-time `daily_coverage`
    rebuild populates that table so the home/status pages return data.

    Cagg refresh is handled out-of-band: the TSDB background policy refreshes
    the last 7 days continuously, and the sync orchestrator runs a whole-
    history refresh after WP6_SYNC_MODE=full. For a manual cagg rebuild,
    the runbook step is:
        CALL refresh_continuous_aggregate('sensors_daily_summary',NULL,NULL)
    """
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.commit()

    await ensure_aggregates(pool, project_column="source")

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT count(*) FROM daily_coverage")
        coverage_row = await cur.fetchone()
        coverage_rows = coverage_row[0] if coverage_row else 0
        await cur.execute("SELECT count(*) FROM readings")
        readings_row = await cur.fetchone()
        readings_rows = readings_row[0] if readings_row else 0
        if coverage_rows == 0 and readings_rows > 0:
            backfilled = await rebuild_daily_coverage(conn)
            await conn.commit()
            logger.info("daily_coverage_backfilled", rows=backfilled)

    logger.info("red_tsdb_schema_ensured")


_EMPTY_READINGS = pd.DataFrame(columns=["device", "sensor", "time", "value"])


async def fetch_data_tsdb(
    sensor_tags: list[str] | None = None,
    device_names: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500_000,
) -> pd.DataFrame:
    """Fetch readings from the red TSDB `readings` table.

    Returns DataFrame with columns: device, sensor, time, value.
    """
    from wp6_data.db.pool import get_pool

    if not sensor_tags:
        return _EMPTY_READINGS.copy()

    conditions = ["sensor_tag = ANY(%(tags)s)"]
    params: dict[str, Any] = {"tags": sensor_tags}
    if device_names:
        conditions.append("device_name = ANY(%(devices)s)")
        params["devices"] = device_names
    if start:
        conditions.append("time >= %(start)s")
        params["start"] = start
    if end:
        conditions.append("time <= %(end)s")
        params["end"] = end
    params["limit"] = limit

    where = " AND ".join(conditions)
    query = f"""
        SELECT device_name AS device, sensor_tag AS sensor, time, value
        FROM readings
        WHERE {where}
        ORDER BY time
        LIMIT %(limit)s
    """

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        records = await cur.fetchall()

    if not records:
        return _EMPTY_READINGS.copy()
    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("time")


async def fetch_sensors_from_cagg(
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Per-sensor reading-count + first/last seen from the cagg.

    Mirrors `blue.deps._fetch_sensors_from_cagg`. The cagg aliases red's
    `source` column to ``project`` in its output (uniform shape across twins);
    we filter on it when `source` is given.
    """
    from wp6_data.db.pool import get_pool

    if source is not None:
        where = "WHERE project = %(source)s"
        params: dict[str, Any] = {"source": source}
    else:
        where = ""
        params = {}

    query = f"""
        SELECT device_name AS device, sensor_tag AS sensor,
               sum(reading_count)  AS readings,
               min(first_reading)  AS earliest,
               max(last_reading)   AS latest
        FROM sensors_daily_summary
        {where}
        GROUP BY device_name, sensor_tag
        ORDER BY readings DESC
    """

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return list(await cur.fetchall())


async def fetch_manual_summary_tsdb() -> dict[str, Any]:
    """Aggregate metadata for manually-uploaded measurements.

    Returns ``{"uploads": {source: last_uploaded_at},
              "measurements": {sensor_tag: last_measure_time}}``.
    Drives the Manual tab's *Last upload* (per-source) and
    *Last measure* (per measurement type) columns. Delegates to the shared,
    twin-agnostic query (promoted out of red so blue shares one provenance
    model); behaviour is unchanged for red.
    """
    from wp6_data.db.pool import get_pool
    from wp6_data.db.queries import fetch_manual_summary

    return await fetch_manual_summary(get_pool())


async def fetch_daily_coverage_from_table() -> list[dict[str, Any]]:
    """Distinct (device, sensor, day) triples from the `daily_coverage` table.

    Replaces the previous `GROUP BY DATE(time)` scan of `readings`; rows are
    written incrementally by ingest paths and rebuilt by the bootstrap.
    """
    from wp6_data.db.pool import get_pool

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT device_name AS device, sensor_tag AS sensor, day "
            "FROM daily_coverage "
            "ORDER BY device, sensor, day"
        )
        return list(await cur.fetchall())


async def fetch_sync_metrics_tsdb() -> list[dict[str, Any]]:
    """Return red's job-run audit rows from `sync_metadata`.

    Shape matches `blue.deps.fetch_sync_metrics` so `shared.routes.status`
    can render them uniformly.
    """
    from wp6_data.db.pool import get_pool

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT endpoint,
                   last_run_at,
                   last_run_success,
                   last_run_duration_sec AS duration_seconds,
                   last_run_records AS records,
                   last_error AS error,
                   last_api_status AS api_status,
                   last_api_error_detail AS api_error_detail,
                   total_runs,
                   total_failures,
                   last_timestamp AS last_data_timestamp
            FROM sync_metadata
            """
        )
        return list(await cur.fetchall())
