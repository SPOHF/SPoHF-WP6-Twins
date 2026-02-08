"""Blue dashboard home page."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.blue import deps
from wp6_data.shared import render_page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home() -> str:
    """Dashboard home page."""
    sensors = deps.fetch_available_sensors()

    # Group sensors by tag
    sensor_tags: dict[str, int] = {}
    for s in sensors:
        tag = s["sensor"]
        if tag not in sensor_tags:
            sensor_tags[tag] = 0
        sensor_tags[tag] += s["readings"]

    sensor_list = "".join(
        f'<li><a href="/chart/{tag}">{tag}</a> ({count:,} readings)</li>'
        for tag, count in sorted(sensor_tags.items(), key=lambda x: -x[1])
    )

    content = f"""
        <h1>WP6 Blue - Sensor Dashboard</h1>
        <h2>Available Sensors</h2>
        <ul>{sensor_list}</ul>
        <h2>Compare Sensors</h2>
        <p><a href="/compare">Custom dual-axis comparison</a></p>
        <h2>Operations</h2>
        <p><a href="/sync-status">Sync status &amp; metrics</a></p>
    """

    return render_page("WP6 Blue - Sensor Dashboard", content)
