"""Shared chart endpoints: unified chart page + type/device redirects."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from wp6_data.shared import render_unified_chart_page, resolve_date_range
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.routes.deps import get_metadata, get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/chart", response_class=HTMLResponse)
async def unified_chart(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Unified interactive chart page with side panel sensor selection."""
    start, end, _, _ = resolve_date_range(start, end)
    return render_unified_chart_page(
        config.title, start, end,
    )


@router.get("/type/{sensor_type}")
async def type_chart(
    sensor_type: str,
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    metadata: Annotated[MetadataRegistry, Depends(get_metadata)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect to unified chart with all sensors of a given type."""
    type_map = metadata.sensor_types()
    sensor_keys = type_map.get(sensor_type, [])
    if not sensor_keys:
        return RedirectResponse(url="/chart")

    available = await provider.fetch_available_sensors()
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
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect device chart to unified /chart with device's sensors."""
    sensors = await provider.fetch_available_sensors()
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
