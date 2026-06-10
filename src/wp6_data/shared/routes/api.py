"""Shared JSON API endpoints for the unified chart page."""

import csv
import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from wp6_data.config import Settings
from wp6_data.db.pool import get_pool
from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.fertigation import resolve_fertigation_csv_path
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.routes.deps import get_metadata, get_provider
from wp6_data.shared.templates import resolve_date_range
from wp6_data.shared.time import to_local_isoformat
from wp6_data.shared.twin import SensorDataProvider

_settings = Settings()
_logger = logging.getLogger(__name__)
_FERT_SOURCE = "fertigation_events"
_FERT_SENSOR = "volume_ml_per_plant"

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


def _fertigation_csv_path():
    """Resolve fertigation events CSV path.

    Priority:
    1) ``WP6_BLUE_FERTIGATION_EVENTS_CSV`` / ``Settings.blue_fertigation_events_csv``
    2) Workspace-relative fallback: uploads-blue/fertigation/fertigation_events.csv
    """
    return resolve_fertigation_csv_path(_settings.blue_fertigation_events_csv)


@router.get("/sensors")
async def list_sensors(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    metadata: Annotated[MetadataRegistry, Depends(get_metadata)],
) -> list[dict[str, str]]:
    """List all available device+sensor combos, for the side panel tree."""
    try:
        sensors = await provider.fetch_available_sensors()
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    flat = [
        {"device": s["device"], "sensor": s["sensor"]}
        for s in sorted(sensors, key=lambda s: (s["sensor"], s["device"]))
    ]
    enriched = metadata.enrich_sensor_list(flat)
    return JSONResponse(
        content=enriched,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/series")
async def get_series(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    device: str = Query(..., description="Device name"),
    sensor: str = Query(..., description="Sensor tag"),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: int = Query(default=None, description="Max records"),
    bkt: int = Query(default=0, description="Aggregation bucket in minutes (0 = raw)"),
    agg: str | None = Query(default=None, description="Aggregation function"),
) -> dict[str, Any]:
    """Fetch time-series data for a single device+sensor combo.

    When ``bkt`` > 0 and ``agg`` is one of avg/min/max/sum, aggregation is
    pushed server-side: the ``limit`` then caps *bucketed* rows (not raw
    readings), so long ranges no longer silently truncate, and each point
    carries a ``count`` of underlying non-null readings for correct
    count-weighted client-side merge of series sharing a label.
    """
    if limit is None:
        limit = _settings.chart_query_limit

    bucket: timedelta | None = None
    if bkt > 0 and agg is not None:
        if agg not in CHART_AGG_FUNCS:
            valid = sorted(CHART_AGG_FUNCS)
            return JSONResponse(
                content={"error": f"Invalid agg {agg!r}; expected one of {valid}"},
                status_code=400,
            )
        bucket = timedelta(minutes=bkt)
    else:
        agg = None  # bkt without agg (or vice-versa) → raw, no partial agg

    _start, _end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await provider.fetch_data(
            sensor_tags=[sensor],
            device_names=[device],
            start=start_dt,
            end=end_dt,
            limit=limit,
            bucket=bucket,
            agg=agg,
        )
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    if df.empty:
        return {"data": [], "truncated": False, "limit": limit}

    truncated = len(df) >= limit
    has_count = "count" in df.columns
    # value_min/value_max ride along only on bucketed responses; the client
    # uses them to shade an optional min/max range band around the line.
    has_spread = "value_min" in df.columns and "value_max" in df.columns
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        t: datetime = row["time"]
        rec: dict[str, Any] = {
            "time": to_local_isoformat(t),
            "value": None if row["value"] is None else float(row["value"]),
        }
        if has_spread:
            vmin, vmax = row["value_min"], row["value_max"]
            rec["min"] = None if vmin is None or pd.isna(vmin) else float(vmin)
            rec["max"] = None if vmax is None or pd.isna(vmax) else float(vmax)
        if has_count:
            rec["count"] = int(row["count"])
        records.append(rec)
    return {"data": records, "truncated": truncated, "limit": limit}


@router.get("/fertigation-events")
async def fertigation_events(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """List farm-wide fertigation event starts.

    Primary source is DB-ingested manual rows (``source=fertigation_events``)
    with ``sensor_tag=volume_ml_per_plant`` and ``value > 0``. Falls back to
    the legacy CSV path when no DB events exist yet.
    """
    in_view_days: list[date] = []
    first_day: date | None = None
    last_day: date | None = None
    total_events = 0
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT MIN(time::date) AS first_day, "
                "MAX(time::date) AS last_day, "
                "COUNT(DISTINCT time::date) AS total_events "
                "FROM readings "
                "WHERE source = %s AND sensor_tag = %s AND value > 0",
                (_FERT_SOURCE, _FERT_SENSOR),
            )
            stats = await cur.fetchone()
            if stats is not None:
                first_day = stats.get("first_day")
                last_day = stats.get("last_day")
                total_events = int(stats.get("total_events") or 0)

            sql = (
                "SELECT DISTINCT time::date AS day "
                "FROM readings "
                "WHERE source = %s AND sensor_tag = %s AND value > 0"
            )
            params: list[Any] = [_FERT_SOURCE, _FERT_SENSOR]
            if start is not None:
                sql += " AND time::date >= %s"
                params.append(start)
            if end is not None:
                sql += " AND time::date <= %s"
                params.append(end)
            sql += " ORDER BY day"
            await cur.execute(
                sql,
                tuple(params),
            )
            in_view_days = [r["day"] for r in await cur.fetchall() if r["day"] is not None]
    except Exception:
        _logger.exception("Fertigation events DB lookup failed; falling back to CSV")
        in_view_days = []
        first_day = None
        last_day = None
        total_events = 0

    if total_events > 0:
        events = [
            {
                "time": to_local_isoformat(
                    datetime.fromisoformat(f"{d.isoformat()}T00:00:00+00:00")
                ),
                "date": d.isoformat(),
            }
            for d in in_view_days
        ]
        return {
            "events": events,
            "source": "db:readings/fertigation_events",
            "first_date": first_day.isoformat() if first_day is not None else None,
            "last_date": last_day.isoformat() if last_day is not None else None,
            "total_events": total_events,
            "in_view_events": len(in_view_days),
        }

    # Legacy fallback path during transition to manual-source ingest.
    path = _fertigation_csv_path()
    if not path.exists():
        return {
            "events": [],
            "source": str(path),
            "first_date": None,
            "last_date": None,
            "total_events": 0,
            "in_view_events": 0,
        }

    all_days: set[date] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                day_raw = (row.get("date") or "").strip()
                if not day_raw:
                    continue
                try:
                    day = date.fromisoformat(day_raw)
                except ValueError:
                    continue

                vol_raw = (row.get("volume_ml_per_plant") or "").strip()
                try:
                    volume = float(vol_raw)
                except ValueError:
                    volume = 0.0
                if volume <= 0:
                    continue
                all_days.add(day)
    except OSError:
        return JSONResponse(
            content={"error": "Failed to read fertigation events CSV"},
            status_code=500,
        )

    in_view_days = [
        d for d in all_days
        if (start is None or d >= start) and (end is None or d <= end)
    ]
    sorted_all = sorted(all_days)

    events = [
        {
            "time": to_local_isoformat(
                datetime.fromisoformat(f"{d.isoformat()}T00:00:00+00:00")
            ),
            "date": d.isoformat(),
        }
        for d in sorted(in_view_days)
    ]
    return {
        "events": events,
        "source": str(path),
        "first_date": sorted_all[0].isoformat() if sorted_all else None,
        "last_date": sorted_all[-1].isoformat() if sorted_all else None,
        "total_events": len(sorted_all),
        "in_view_events": len(in_view_days),
    }
