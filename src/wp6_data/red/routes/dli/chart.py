"""GET /dli/chart — Simple PAR chart showing light above lamps vs under lamps."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR
from wp6_data.shared import make_line_chart, render_chart_page, render_page, resolve_date_range

router = APIRouter()


@router.get("/chart", response_class=HTMLResponse)
async def dli_chart(
    start: Annotated[date | None, Query(description="Start date")] = None,
    end: Annotated[date | None, Query(description="End date")] = None,
) -> str:
    """Simple PAR chart showing light above lamps vs under lamps."""
    if not deps.db:
        return render_page("DLI Chart - WP6 Red", "<h1>Database not connected</h1>",
                          show_back_link=True, back_url="/dli")

    start, end, start_dt, end_dt = resolve_date_range(start, end)

    try:
        df = await deps.db.get_par_readings(
            device_ids=[NATURAL_LIGHT_SENSOR, TOTAL_LIGHT_SENSOR], start=start_dt, end=end_dt
        )
    except Exception as e:
        return render_page("DLI Chart - WP6 Red", f"<h1>Error: {e}</h1>",
                          show_back_link=True, back_url="/dli")

    # Rename device IDs to friendly labels for the chart legend
    device_labels = {
        NATURAL_LIGHT_SENSOR: "Above Lamps (natural)",
        TOTAL_LIGHT_SENSOR: "Under Lamps (total)",
    }
    if not df.empty:
        df = df.copy()
        df["device"] = df["device"].map(device_labels).fillna(df["device"])

    fig = make_line_chart(df, title="PAR - Above Lamps vs Under Lamps")

    return render_chart_page(df, fig, "DLI Chart - WP6 Red", start, end, back_url="/dli")
