"""Blue dashboard chart endpoint."""

from datetime import date
from types import ModuleType
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.blue.datasource import GetActiveSource
from wp6_data.shared import (
    make_dual_axis_chart,
    make_line_chart,
    render_chart_page,
    resolve_date_range,
)
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/chart/{sensors}", response_class=HTMLResponse)
async def chart(
    sensors: str,
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    dual: bool = Query(False, description="Use dual y-axis for 2 sensors"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Render chart for specified sensors."""
    source, source_name = active_source
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    sensor_list = [s.strip() for s in sensors.split(",")]
    df = source.fetch_data(sensor_tags=sensor_list, start=start_dt, end=end_dt)

    if dual and len(sensor_list) == 2:
        fig = make_dual_axis_chart(df, sensor_list[0], sensor_list[1])
    else:
        fig = make_line_chart(df)

    return render_chart_page(
        df, fig, f"{sensors} - WP6 Blue", start, end, data_source=source_name,
    )


@router.get("/device/{device}", response_class=HTMLResponse)
async def device_chart(
    device: str,
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Render chart for all sensors of a specific device."""
    source, source_name = active_source
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    df = source.fetch_data(
        device_names=[device], start=start_dt, end=end_dt,
    )

    tags = sorted(df["sensor"].unique()) if not df.empty else []
    if len(tags) == 2:
        fig = make_dual_axis_chart(df, tags[0], tags[1])
    else:
        fig = make_line_chart(df, title=device)

    return render_chart_page(
        df, fig, f"{device} - WP6 Blue", start, end, data_source=source_name,
    )
