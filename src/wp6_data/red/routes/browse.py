"""Red dashboard sensor browsing endpoints."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from wp6_data.red import deps
from wp6_data.red.db import MEASUREMENTS_TO_TABLES, SENSOR_TABLES
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/measurement/{measurement}")
async def measurement_view(
    measurement: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect to unified chart with all devices that have this measurement."""
    if not deps.db or measurement not in MEASUREMENTS_TO_TABLES:
        return RedirectResponse(url="/chart")

    tables = MEASUREMENTS_TO_TABLES[measurement]
    series: list[str] = []
    for table in tables:
        devices = await deps.db.get_devices_for_table(table)
        for device in devices:
            series.append(f"{device}:{measurement}")

    params: dict[str, str] = {"s": ",".join(series)}
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    return RedirectResponse(url=f"/chart?{urlencode(params)}")


@router.get("/type/{sensor_type}")
async def type_view(
    sensor_type: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect to unified chart with all measurements of a given type."""
    if not deps.db:
        return RedirectResponse(url="/chart")

    # Find all measurement keys that belong to this type
    type_map = deps.metadata.sensor_types()
    measurements = type_map.get(sensor_type, [])
    if not measurements:
        return RedirectResponse(url="/chart")

    series: list[str] = []
    for measurement in measurements:
        tables = MEASUREMENTS_TO_TABLES.get(measurement, [])
        for table in tables:
            devices = await deps.db.get_devices_for_table(table)
            for device in devices:
                series.append(f"{device}:{measurement}")

    params: dict[str, str] = {"s": ",".join(series)}
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    return RedirectResponse(url=f"/chart?{urlencode(params)}")


@router.get("/table/{table}")
async def table_view(table: str) -> RedirectResponse:
    """Redirect to unified chart for a sensor table."""
    if not deps.db or table not in SENSOR_TABLES:
        return RedirectResponse(url="/chart")

    devices = await deps.db.get_devices_for_table(table)
    measurements = SENSOR_TABLES[table]
    series = [
        f"{device}:{m}" for device in devices for m in measurements
    ]
    return RedirectResponse(url=f"/chart?s={','.join(series)}")
