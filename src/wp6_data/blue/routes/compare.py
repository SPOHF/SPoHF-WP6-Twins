"""Blue dashboard compare endpoints."""

from datetime import date
from types import ModuleType
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.blue.datasource import GetActiveSource
from wp6_data.shared import (
    render_compare_form,
    render_comparison_result,
    render_page,
    resolve_date_range,
)
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/compare", response_class=HTMLResponse)
async def compare_form(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
) -> str:
    """Form to select two device/sensor pairs for a custom dual-axis chart."""
    source, source_name = active_source
    sensors = await source.fetch_available_sensors()

    # Build device -> [sensor tags] mapping
    device_data: dict[str, list[str]] = {}
    for s in sensors:
        device_data.setdefault(s["device"], [])
        if s["sensor"] not in device_data[s["device"]]:
            device_data[s["device"]].append(s["sensor"])

    form_html = render_compare_form(device_data, action_url="/compare/chart")
    content = f"""
        <h1>Custom Compare</h1>
        <p>Select two device/sensor combinations to plot on a dual y-axis chart.</p>
        {form_html}
    """

    return render_page(
        "Custom Compare - WP6 Blue", content,
        show_back_link=True, data_source=source_name,
    )


@router.get("/compare/chart", response_class=HTMLResponse)
async def compare_chart(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    left_device: str = Query(...),
    left_measurement: str = Query(...),
    right_device: str = Query(""),
    right_measurement: str = Query(""),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Render a comparison chart for one or two device/sensor pairs."""
    source, source_name = active_source
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    left_df = await source.fetch_data(sensor_tags=[left_measurement], start=start_dt, end=end_dt)
    if not left_df.empty:
        left_df = left_df[left_df["device"] == left_device]

    if right_device and right_measurement:
        right_df = await source.fetch_data(
            sensor_tags=[right_measurement], start=start_dt, end=end_dt,
        )
        if not right_df.empty:
            right_df = right_df[right_df["device"] == right_device]
    else:
        right_df = pd.DataFrame(columns=["device", "sensor", "time", "value"])

    return render_comparison_result(
        left_df, right_df,
        left_device, left_measurement,
        right_device, right_measurement,
        start, end,
        "Compare - WP6 Blue",
        data_source=source_name,
    )
