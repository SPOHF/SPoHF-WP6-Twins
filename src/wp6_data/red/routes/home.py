"""Red dashboard home page."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.db import MEASUREMENT_GROUPS, MEASUREMENTS_TO_TABLES
from wp6_data.shared import render_card, render_page, render_table
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/", response_class=HTMLResponse)
async def home(user: str = Depends(verify_session_user)) -> str:
    """Dashboard home page - list available sensors."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>")

    sensors = await deps.db.get_available_sensors()
    export_meta = deps.get_export_metadata()
    available_exports = export_meta.get("tables", {}) if export_meta else {}

    # Sensor types table
    sensor_rows = []
    for s in sensors:
        table = s["table"]
        measurements = ", ".join(s["measurements"])
        if table in available_exports:
            export_ts = available_exports[table][:16].replace("T", " ")
            download_link = (
                f'<a href="/download/{table}" title="Download CSV">CSV</a> '
                f"<small>({export_ts})</small>"
            )
        else:
            download_link = "-"
        sensor_rows.append([
            f'<a href="/table/{table}">{table}</a>',
            str(s["devices"]),
            f'{s["readings"]:,}',
            measurements,
            download_link,
        ])

    sensor_table = render_table(
        ["Device Type", "Devices", "Readings", "Measurements", "Download"],
        sensor_rows,
    )

    # Measurement types table (hide items that are part of a group)
    grouped_measurements = set()
    for group_cols in MEASUREMENT_GROUPS.values():
        grouped_measurements.update(group_cols)

    measurement_rows = [
        [
            f'<a href="/measurement/{measurement}">{measurement}</a>',
            ", ".join(sorted(tables)),
        ]
        for measurement, tables in sorted(MEASUREMENTS_TO_TABLES.items())
        if measurement not in grouped_measurements
    ]
    measurement_table = render_table(
        ["Measurement", "Available in Device"],
        measurement_rows,
    )

    content = f"""
        <h1>WP6 Red - Sensor Dashboard</h1>

        {render_card(
            "Light Analysis (DLI)",
            '<a href="/dli" role="button">DLI Dashboard</a>',
            description="Daily Light Integral analysis and optimization tools.",
        )}

        {render_card(
            "Custom Compare",
            '<a href="/compare" role="button">Compare</a>',
            description="Create a custom dual-axis chart "
            "by selecting two sensor/measurement combinations.",
        )}

        {render_card("Compare by Measurement Type", measurement_table,
                      description="View all sensors measuring the same thing:")}

        {render_card(
            "Browse by Device Type",
            sensor_table + deps._export_info_html(export_meta),
        )}

        <a href="/static/red/sensor_locations.docx" download role="button" class="outline"
           style="width:100%">Download Sensor Device Identification (docx)</a>
    """

    return render_page("WP6 Red - Sensor Dashboard", content)
