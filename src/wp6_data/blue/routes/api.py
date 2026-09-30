"""Blue-only JSON API endpoints."""

import csv
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from wp6_data.blue import deps
from wp6_data.blue.fertigation import (
    load_fertigation_csv,
    parse_fertigation_event_days,
)
from wp6_data.config import Settings
from wp6_data.db import get_pool
from wp6_data.shared.auth import verify_session_user

_settings = Settings()
_FERT_CSV_SOURCE = "csv:fertigation_events"

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


async def _fertigation_csv() -> bytes | None:
    """The fertigation events CSV for blue, or None when there isn't one."""
    return await load_fertigation_csv(
        _settings.blue_fertigation_events_csv, deps.UPLOADS_STORE, get_pool(),
    )


@router.get("/fertigation-events")
async def fertigation_events(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """List farm-wide fertigation event starts from the blue CSV source."""
    raw = await _fertigation_csv()
    if raw is None:
        return {
            "events": [],
            "source": _FERT_CSV_SOURCE,
            "first_date": None,
            "last_date": None,
            "total_events": 0,
            "in_view_events": 0,
        }

    try:
        sorted_all = parse_fertigation_event_days(raw)
    except (UnicodeError, csv.Error):
        return JSONResponse(
            content={"error": "Failed to read fertigation events CSV"},
            status_code=500,
        )

    in_view_days = [
        d for d in sorted_all
        if (start is None or d >= start) and (end is None or d <= end)
    ]

    events = [
        {
            "time": f"{d.isoformat()}T00:00:00.000000",
            "date": d.isoformat(),
        }
        for d in in_view_days
    ]
    return {
        "events": events,
        "source": _FERT_CSV_SOURCE,
        "first_date": sorted_all[0].isoformat() if sorted_all else None,
        "last_date": sorted_all[-1].isoformat() if sorted_all else None,
        "total_events": len(sorted_all),
        "in_view_events": len(in_view_days),
    }
