"""Shared JSON API endpoints for the unified chart page."""

import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from wp6_data.config import Settings
from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.routes.deps import get_metadata, get_provider
from wp6_data.shared.templates import resolve_date_range
from wp6_data.shared.time import to_local_isoformat
from wp6_data.shared.twin import SensorDataProvider

_settings = Settings()

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


def _fertigation_csv_path() -> Path:
    """Resolve fertigation events CSV path.

    Priority:
    1) ``WP6_BLUE_FERTIGATION_EVENTS_CSV`` / ``Settings.blue_fertigation_events_csv``
    2) Workspace-relative fallback: uploads-blue/fertigation/fertigation_events.csv
    """
    configured = (_settings.blue_fertigation_events_csv or "").strip()
    if configured:
        p = Path(configured)
        if p.is_absolute():
            return p
        return Path.cwd() / p
    return Path.cwd() / "uploads-blue" / "fertigation" / "fertigation_events.csv"


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
    """List farm-wide fertigation event starts from CSV.

    The source file has one row per treatment per day; this endpoint returns
    unique event starts per date. Rows with ``volume_ml_per_plant <= 0`` are
    ignored by design.
    """
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
        {"time": f"{d.isoformat()}T00:00:00", "date": d.isoformat()}
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
