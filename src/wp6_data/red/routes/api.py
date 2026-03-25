"""Red dashboard JSON API endpoints for the unified chart page."""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from wp6_data.config import Settings
from wp6_data.red import deps
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.templates import resolve_date_range

_settings = Settings()

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


@router.get("/sensors")
async def list_sensors() -> list[dict[str, str]]:
    """List all available device+sensor combos, for the side panel tree."""
    if not deps.db:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    devices = await deps.db.get_all_devices()
    result: list[dict[str, str]] = []
    for device_id, info in sorted(devices.items()):
        for measurement in sorted(info["measurements"]):
            result.append({"device": device_id, "sensor": measurement})
    return JSONResponse(
        content=result,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/series")
async def get_series(
    device: str = Query(..., description="Device ID"),
    sensor: str = Query(..., description="Measurement name"),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: int = Query(default=None, description="Max records"),
) -> dict[str, Any]:
    """Fetch time-series data for a single device+sensor combo."""
    if not deps.db:
        return JSONResponse(content={"error": "Database not connected"}, status_code=503)

    if limit is None:
        limit = _settings.chart_query_limit

    _start, _end, start_dt, end_dt = resolve_date_range(start, end)

    df = await deps.db.get_readings_for_comparison(
        device, sensor, start=start_dt, end=end_dt, limit=limit,
    )

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
