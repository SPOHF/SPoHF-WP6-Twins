"""GET /monitor/light — Redirect to unified chart with all PAR sensors."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from wp6_data.shared.routes.deps import get_provider
from wp6_data.shared.twin import SensorDataProvider

router = APIRouter()

PAR_SENSOR = "par"


@router.get("/light")
async def light_chart(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> RedirectResponse:
    """Redirect to unified chart pre-loaded with all PAR sensors."""
    available = await provider.fetch_available_sensors()
    series = sorted(
        f"{s['device']}:{s['sensor']}"
        for s in available
        if s["sensor"] == PAR_SENSOR
    )

    params: dict[str, str] = {}
    if series:
        params["s"] = ",".join(series)
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()

    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/chart{qs}")
