"""Red dashboard chart endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.shared import (
    make_dual_axis_chart,
    make_line_chart,
    render_chart_page,
    render_page,
    resolve_date_range,
)
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/chart/{table}", response_class=HTMLResponse)
async def chart_all(
    table: str,
    limit: int = Query(50000, description="Max records to fetch"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Chart all devices for a sensor table."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await deps.db.get_readings(table, start=start_dt, end=end_dt, limit=limit)
    except ValueError as e:
        return render_page(
            f"{table} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    fig = make_line_chart(df, title=f"{table} - All Devices")

    return render_chart_page(
        df, fig, f"{table} - WP6 Red", start, end, back_url=f"/table/{table}",
    )


@router.get("/chart/{table}/{device_id}", response_class=HTMLResponse)
async def chart_device(
    table: str,
    device_id: str,
    limit: int = Query(50000, description="Max records to fetch"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Chart a specific device."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await deps.db.get_readings(
            table, device_id=device_id, start=start_dt, end=end_dt, limit=limit,
        )
    except ValueError as e:
        return render_page(
            f"{device_id} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    # Check if we can do dual axis (2 different measurements)
    sensors = df["sensor"].unique() if not df.empty else []
    if len(sensors) == 2:
        fig = make_dual_axis_chart(df, sensors[0], sensors[1], title=f"{table} - {device_id}")
    else:
        fig = make_line_chart(df, title=f"{table} - {device_id}")

    return render_chart_page(
        df, fig, f"{device_id} - WP6 Red", start, end, back_url=f"/table/{table}",
    )
