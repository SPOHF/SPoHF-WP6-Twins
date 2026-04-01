"""Blue-specific chart redirect: sensor name grouping."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/chart/{sensors}")
async def chart(
    sensors: str,
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> RedirectResponse:
    """Redirect sensor chart to unified /chart page."""
    sensor_list = [s.strip() for s in sensors.split(",")]
    available = await provider.fetch_available_sensors()
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
