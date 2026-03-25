"""Blue dashboard JSON API endpoints for the unified chart page."""

from datetime import date, datetime
from types import ModuleType
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from wp6_data.blue import deps
from wp6_data.blue.datasource import GetActiveSource
from wp6_data.config import Settings
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.templates import resolve_date_range

_settings = Settings()

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


@router.get("/sensors")
async def list_sensors(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
) -> list[dict[str, str]]:
    """List all available device+sensor combos, for the side panel tree."""
    source, _ = active_source
    try:
        sensors = await source.fetch_available_sensors()
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    flat = [
        {"device": s["device"], "sensor": s["sensor"]}
        for s in sorted(sensors, key=lambda s: (s["sensor"], s["device"]))
    ]
    enriched = deps.metadata.enrich_sensor_list(flat)
    return JSONResponse(
        content=enriched,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/series")
async def get_series(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    device: str = Query(..., description="Device name"),
    sensor: str = Query(..., description="Sensor tag"),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: int = Query(default=None, description="Max records"),
) -> dict[str, Any]:
    """Fetch time-series data for a single device+sensor combo."""
    source, _ = active_source

    if limit is None:
        limit = _settings.chart_query_limit

    _start, _end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await source.fetch_data(
            sensor_tags=[sensor],
            device_names=[device],
            start=start_dt,
            end=end_dt,
            limit=limit,
        )
    except Exception:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    if df.empty:
        return {"data": [], "truncated": False}

    truncated = len(df) >= limit
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        t: datetime = row["time"]
        records.append({
            "time": t.isoformat(),
            "value": None if row["value"] is None else float(row["value"]),
        })
    return {"data": records, "truncated": truncated, "limit": limit}
