"""Red dashboard home page."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.shared import build_home_tables, render_card, render_page
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])

PAGE_TITLE = "SPoHF Red Digital Twin"


@router.get("/", response_class=HTMLResponse)
async def home(user: str = Depends(verify_session_user)) -> str:
    """Dashboard home page - list available sensors."""
    if not deps.db:
        return render_page(PAGE_TITLE, "<h1>Database not connected</h1>")

    all_devices = await deps.db.get_all_devices()
    sensors = await deps.db.get_available_sensors()
    export_meta = deps.get_export_metadata()
    available_exports = export_meta.get("devices", {}) if export_meta else {}

    # Build table → readings lookup for per-device reading estimates
    table_readings: dict[str, int] = {}
    table_device_count: dict[str, int] = {}
    for s in sensors:
        table_readings[s["table"]] = s["readings"]
        table_device_count[s["table"]] = s["devices"]

    # Normalize into common format: {device: {sensors, readings}}
    device_data: dict[str, dict] = {}
    for device_id, info in all_devices.items():
        total = sum(
            table_readings.get(t, 0) // max(table_device_count.get(t, 1), 1)
            for t in info["tables"]
        )
        device_data[device_id] = {
            "sensors": info["measurements"],
            "readings": total,
        }

    sensor_table, device_table = build_home_tables(
        deps.metadata, device_data, available_exports,
    )

    content = f"""
        <h1>{PAGE_TITLE}</h1>

        {render_card(
            "Dashboard",
            '<div style="display:flex;gap:0.5rem">'
            '<a href="/dashboard" role="button">My Dashboard</a>'
            '<a href="/chart" role="button" class="outline">'
            'New Chart</a></div>',
            description="Your bookmarked charts in one view. "
            "Or create a new chart from scratch.",
            card_class="card card-bg card-bg-chart",
        )}

        {render_card(
            "Light Analysis (DLI)",
            '<a href="/dli" role="button">DLI Dashboard</a>',
            description="Daily Light Integral analysis and optimization tools.",
            card_class="card-bg card-bg-sun",
        )}

        {render_card("Explore by Sensor Type", sensor_table)}

        {render_card("Explore by Device", device_table)}

        <a href="/static/red/sensor_locations.docx" download role="button" class="outline"
           style="width:100%">Download Sensor Device Identification (docx)</a>
    """

    return render_page(PAGE_TITLE, content)
