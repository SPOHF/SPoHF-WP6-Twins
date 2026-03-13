"""Red dashboard compare endpoints."""

from datetime import date
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.shared import (
    render_compare_form,
    render_comparison_result,
    render_page,
    resolve_date_range,
)

router = APIRouter(dependencies=[Depends(deps.verify_auth)])


@router.get("/compare", response_class=HTMLResponse)
async def compare_form() -> str:
    """Form to select two device/measurement pairs for a custom dual-axis chart."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    devices = await deps.db.get_all_devices()
    device_data = {did: info["measurements"] for did, info in devices.items()}

    form_html = render_compare_form(device_data, action_url="/compare/chart")
    content = f"""
        <h1>Custom Compare</h1>
        <p>Select two device/measurement combinations to plot on a dual y-axis chart.</p>
        {form_html}
    """

    return render_page("Custom Compare - WP6 Red", content, show_back_link=True)


@router.get("/compare/chart", response_class=HTMLResponse)
async def compare_chart(
    left_device: str = Query(...),
    left_measurement: str = Query(...),
    right_device: str = Query(""),
    right_measurement: str = Query(""),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Render a dual-axis chart for two user-selected device/measurement pairs."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    has_right = bool(right_device and right_measurement)

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        left_df = await deps.db.get_readings_for_comparison(
            left_device, left_measurement, start=start_dt, end=end_dt,
        )
        right_df = (
            await deps.db.get_readings_for_comparison(
                right_device, right_measurement, start=start_dt, end=end_dt,
            )
            if has_right
            else pd.DataFrame(columns=["device", "sensor", "time", "value"])
        )
    except ValueError as e:
        return render_page(
            "Compare - WP6 Red", f"<h1>Error: {e}</h1>",
            show_back_link=True, back_url="/compare",
        )

    return render_comparison_result(
        left_df, right_df,
        left_device, left_measurement,
        right_device, right_measurement,
        start, end,
        "Compare - WP6 Red",
    )
