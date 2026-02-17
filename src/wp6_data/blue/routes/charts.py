"""Blue dashboard chart endpoint."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.blue import deps
from wp6_data.shared import (
    make_dual_axis_chart,
    make_line_chart,
    render_chart_page,
    resolve_date_range,
)

router = APIRouter()


@router.get("/chart/{sensors}", response_class=HTMLResponse)
async def chart(
    sensors: str,
    dual: bool = Query(False, description="Use dual y-axis for 2 sensors"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Render chart for specified sensors."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    sensor_list = [s.strip() for s in sensors.split(",")]
    df = deps.fetch_data(sensor_tags=sensor_list, start=start_dt, end=end_dt)

    if dual and len(sensor_list) == 2:
        fig = make_dual_axis_chart(df, sensor_list[0], sensor_list[1])
    else:
        fig = make_line_chart(df)

    return render_chart_page(df, fig, f"{sensors} - WP6 Blue", start, end)


@router.get("/device/{device}", response_class=HTMLResponse)
async def device_chart(
    device: str,
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Render chart for all sensors of a specific device."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    df = deps.fetch_data(
        device_names=[device], start=start_dt, end=end_dt,
    )

    tags = sorted(df["sensor"].unique()) if not df.empty else []
    if len(tags) == 2:
        fig = make_dual_axis_chart(df, tags[0], tags[1])
    else:
        fig = make_line_chart(df, title=device)

    return render_chart_page(df, fig, f"{device} - WP6 Blue", start, end)
