"""Blue dashboard chart endpoints."""

from datetime import date
from types import ModuleType
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from wp6_data.blue import deps
from wp6_data.blue.datasource import GetActiveSource
from wp6_data.shared import render_unified_chart_page, resolve_date_range
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "SPoHF Blue"

@router.get("/chart", response_class=HTMLResponse)
async def unified_chart(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Unified interactive chart page with side panel sensor selection."""
    _, source_name = active_source
    start, end, _, _ = resolve_date_range(start, end)
    return render_unified_chart_page(
        PAGE_TITLE, start, end, data_source=source_name,
    )


@router.get("/chart/{sensors}")
async def chart(
    sensors: str,
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect sensor chart to unified /chart page."""
    source, _ = active_source
    sensor_list = [s.strip() for s in sensors.split(",")]
    available = await source.fetch_available_sensors()
    series = [
        f"{s['device']}:{s['sensor']}"
        for s in available
        if s["sensor"] in sensor_list
    ]

    params: dict[str, str] = {}
    if series:
        params["s"] = ",".join(sorted(series))
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/chart{qs}")


@router.get("/type/{sensor_type}")
async def type_chart(
    sensor_type: str,
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect to unified chart with all sensors of a given type."""
    source, _ = active_source
    type_map = deps.metadata.sensor_types()
    sensor_keys = type_map.get(sensor_type, [])
    if not sensor_keys:
        return RedirectResponse(url="/chart")

    available = await source.fetch_available_sensors()
    series = [
        f"{s['device']}:{s['sensor']}"
        for s in available
        if s["sensor"] in sensor_keys
    ]

    params: dict[str, str] = {}
    if series:
        params["s"] = ",".join(sorted(series))
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/chart{qs}")


@router.get("/device/{device}")
async def device_chart(
    device: str,
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect device chart to unified /chart with device's sensors."""
    source, _ = active_source
    sensors = await source.fetch_available_sensors()
    device_sensors = [s["sensor"] for s in sensors if s["device"] == device]
    series = [f"{device}:{sensor}" for sensor in sorted(device_sensors)]

    params: dict[str, str] = {}
    if series:
        params["s"] = ",".join(series)
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/chart{qs}")
