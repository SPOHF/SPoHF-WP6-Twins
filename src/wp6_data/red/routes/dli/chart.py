"""GET /dli/chart — Redirect to unified chart with PAR sensors."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from wp6_data.red.dli import NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR

router = APIRouter()


@router.get("/chart")
async def dli_chart(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> RedirectResponse:
    """Redirect to unified chart with PAR above vs under lamps."""
    params: dict[str, str] = {
        "s": f"{NATURAL_LIGHT_SENSOR}:par",
        "r": f"{TOTAL_LIGHT_SENSOR}:par",
    }
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    return RedirectResponse(url=f"/chart?{urlencode(params)}")
