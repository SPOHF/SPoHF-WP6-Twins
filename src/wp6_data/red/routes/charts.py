"""Red-specific chart redirects: table-based sensor grouping."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from wp6_data.red import deps
from wp6_data.red.db import SENSOR_TABLES
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/chart/{table}")
async def chart_all(
    table: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect to unified chart with all devices for a sensor table."""
    if not deps.db or table not in SENSOR_TABLES:
        return RedirectResponse(url="/chart")

    devices = await deps.db.get_devices_for_table(table)
    measurements = SENSOR_TABLES[table]
    series = [
        f"{device}:{m}" for device in devices for m in measurements
    ]
    params: dict[str, str] = {"s": ",".join(series)}
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    return RedirectResponse(url=f"/chart?{urlencode(params)}")


@router.get("/chart/{table}/{device_id}")
async def chart_device(
    table: str,
    device_id: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect to unified chart with a specific device's sensors."""
    if not deps.db or table not in SENSOR_TABLES:
        return RedirectResponse(url="/chart")

    measurements = SENSOR_TABLES[table]
    series = [f"{device_id}:{m}" for m in measurements]
    params: dict[str, str] = {"s": ",".join(series)}
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    return RedirectResponse(url=f"/chart?{urlencode(params)}")
