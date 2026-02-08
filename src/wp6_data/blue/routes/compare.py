"""Blue dashboard compare endpoints."""

from datetime import date
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.blue import deps
from wp6_data.shared import (
    render_compare_form,
    render_comparison_result,
    render_page,
    resolve_date_range,
)

router = APIRouter()


@router.get("/compare", response_class=HTMLResponse)
async def compare_form() -> str:
    """Form to select two device/sensor pairs for a custom dual-axis chart."""
    sensors = deps.fetch_available_sensors()

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

    return render_page("Custom Compare - WP6 Blue", content, show_back_link=True)


@router.get("/compare/chart", response_class=HTMLResponse)
async def compare_chart(
    left_device: str = Query(...),
    left_measurement: str = Query(...),
    right_device: str = Query(""),
    right_measurement: str = Query(""),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Render a comparison chart for one or two device/sensor pairs."""
    start, end, start_dt, end_dt = resolve_date_range(start, end)

    left_df = deps.fetch_data(sensor_tags=[left_measurement], start=start_dt, end=end_dt)
    if not left_df.empty:
        left_df = left_df[left_df["device"] == left_device]

    if right_device and right_measurement:
        right_df = deps.fetch_data(sensor_tags=[right_measurement], start=start_dt, end=end_dt)
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
    )
