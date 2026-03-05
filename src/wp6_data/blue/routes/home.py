"""Blue dashboard home page."""

from types import ModuleType
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.blue.datasource import GetActiveSource
from wp6_data.shared import render_card, render_page, render_table
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/", response_class=HTMLResponse)
async def home(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
) -> str:
    """Dashboard home page."""
    source, source_name = active_source
    sensors = await source.fetch_available_sensors()

    # Group by sensor tag: total readings
    sensor_tags: dict[str, int] = {}
    # Group by device: set of sensor tags + total readings
    device_info: dict[str, dict] = {}
    for s in sensors:
        tag = s["sensor"]
        device = s["device"]
        readings = s["readings"]
        sensor_tags[tag] = sensor_tags.get(tag, 0) + readings
        info = device_info.setdefault(device, {"tags": set(), "readings": 0})
        info["tags"].add(tag)
        info["readings"] += readings

    # Sensor tags table
    sensor_rows = [
        [f'<a href="/chart/{tag}">{tag}</a>', f"{count:,}"]
        for tag, count in sorted(sensor_tags.items(), key=lambda x: -x[1])
    ]
    sensor_table = render_table(["Sensor Tag", "Readings"], sensor_rows)

    # Devices table
    device_rows = [
        [
            f'<a href="/device/{device}">{device}</a>',
            ", ".join(sorted(info["tags"])),
            f'{info["readings"]:,}',
        ]
        for device, info in sorted(device_info.items())
    ]
    device_table = render_table(["Device", "Sensors", "Readings"], device_rows)

    content = f"""
        <h1>WP6 Blue - Sensor Dashboard</h1>

        {render_card(
            "Custom Compare",
            '<a href="/compare" role="button">Compare</a>',
            description="Create a custom dual-axis chart "
            "by selecting two sensor/device combinations.",
        )}

        {render_card("Browse by Sensor Tag", sensor_table)}

        {render_card("Browse by Device", device_table)}

        {render_card(
            "Status &amp; Coverage",
            '<a href="/status" role="button">View Status</a>',
            description="Sync status, data coverage timeline, "
            "and maintenance tools.",
        )}
    """

    return render_page("WP6 Blue - Sensor Dashboard", content, data_source=source_name)
