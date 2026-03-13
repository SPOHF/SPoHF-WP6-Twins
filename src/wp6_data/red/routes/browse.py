"""Red dashboard sensor browsing endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.db import MEASUREMENTS_TO_TABLES
from wp6_data.shared import make_line_chart, render_chart_page, render_page, resolve_date_range
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/measurement/{measurement}", response_class=HTMLResponse)
async def measurement_view(
    measurement: str,
    limit: int = Query(100000, description="Max records per sensor table"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Chart a measurement type across all sensors that have it."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    if measurement not in MEASUREMENTS_TO_TABLES:
        return render_page(
            f"{measurement} - WP6 Red",
            f"<h1>Unknown measurement: {measurement}</h1>",
            show_back_link=True,
        )

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await deps.db.get_readings_by_measurement(
            measurement, start=start_dt, end=end_dt, limit_per_table=limit,
        )
    except Exception as e:
        return render_page(
            f"{measurement} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
        )

    tables = MEASUREMENTS_TO_TABLES[measurement]
    fig = make_line_chart(df, title=f"{measurement} - All Sensors ({', '.join(tables)})")

    return render_chart_page(df, fig, f"{measurement} - WP6 Red", start, end)


@router.get("/table/{table}", response_class=HTMLResponse)
async def table_view(table: str) -> str:
    """Show devices for a sensor table."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    try:
        devices = await deps.db.get_devices_for_table(table)
    except ValueError as e:
        return render_page(
            f"{table} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
        )

    device_list = "".join(
        f'<li><a href="/chart/{table}/{device}">{device}</a></li>' for device in devices
    )

    content = f"""
        <h1>{table}</h1>
        <h2>Devices</h2>
        <ul>{device_list}</ul>
        <h2>View All Devices</h2>
        <p><a href="/chart/{table}">Combined chart (all devices)</a></p>
    """

    return render_page(f"{table} - WP6 Red", content, show_back_link=True)
