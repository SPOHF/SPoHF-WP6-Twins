"""Blue dashboard home page."""

from types import ModuleType
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.blue import deps
from wp6_data.blue.datasource import GetActiveSource
from wp6_data.blue.deps import get_export_metadata
from wp6_data.shared import build_home_tables, render_card, render_page
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/", response_class=HTMLResponse)
async def home(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
) -> str:
    """Dashboard home page."""
    source, source_name = active_source
    sensors = await source.fetch_available_sensors()
    show_exports = source_name == "spohf-datalake"
    if show_exports:
        export_meta = get_export_metadata()
        available_exports = export_meta.get("devices", {}) if export_meta else {}
    else:
        available_exports = {}

    # Normalize into common format: {device: {sensors, readings}}
    device_data: dict[str, dict] = {}
    for s in sensors:
        info = device_data.setdefault(
            s["device"], {"sensors": set(), "readings": 0},
        )
        info["sensors"].add(s["sensor"])
        info["readings"] += s["readings"]
    # Convert sensor sets to lists for the shared builder
    for info in device_data.values():
        info["sensors"] = list(info["sensors"])

    sensor_table, device_table = build_home_tables(
        deps.metadata, device_data, available_exports,
    )

    content = f"""
        <h1>SPoHF Blue Digital Twin</h1>

        {render_card(
            "Interactive Chart",
            '<a href="/chart" role="button">Chart</a>',
            description="Select any sensors and devices to plot "
            "on a customizable dual-axis chart.",
        )}

        {render_card("Browse by Sensor Type", sensor_table)}

        {render_card("Browse by Device", device_table)}

        {render_card(
            "Status &amp; Coverage",
            '<a href="/status" role="button">View Status</a>',
            description="Sync status, data coverage timeline, "
            "and maintenance tools.",
        )}
    """

    return render_page("SPoHF Blue Digital Twin", content, data_source=source_name)
