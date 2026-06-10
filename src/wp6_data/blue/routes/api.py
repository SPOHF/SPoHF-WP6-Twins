"""Blue-only JSON API endpoints."""

import csv
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from wp6_data.blue.fertigation import (
    load_fertigation_event_days,
    resolve_fertigation_csv_path,
)
from wp6_data.config import Settings
from wp6_data.shared.auth import verify_session_user

_settings = Settings()
_FERT_CSV_SOURCE = "csv:fertigation_events"

router = APIRouter(prefix="/api", dependencies=[Depends(verify_session_user)])


def _fertigation_csv_path():
    """Resolve fertigation events CSV path for blue."""
    return resolve_fertigation_csv_path(_settings.blue_fertigation_events_csv)


@router.get("/fertigation-events")
async def fertigation_events(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """List farm-wide fertigation event starts from the blue CSV source."""
    path = _fertigation_csv_path()
    if not path.exists():
        return {
            "events": [],
            "source": _FERT_CSV_SOURCE,
            "first_date": None,
            "last_date": None,
            "total_events": 0,
            "in_view_events": 0,
        }

    try:
        sorted_all = load_fertigation_event_days(path)
    except (OSError, UnicodeError, csv.Error):
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
