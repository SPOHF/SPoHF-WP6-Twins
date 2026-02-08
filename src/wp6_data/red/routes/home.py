"""Red dashboard home page."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.db import MEASUREMENT_GROUPS, MEASUREMENTS_TO_TABLES
from wp6_data.shared import render_page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(user: str = Depends(deps.verify_auth)) -> str:
    """Dashboard home page - list available sensors."""
    if not deps.db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>")

    sensors = await deps.db.get_available_sensors()
    export_meta = deps.get_export_metadata()
    available_exports = export_meta.get("tables", {}) if export_meta else {}

    # Build sensor list HTML
    sensor_rows = []
    for s in sensors:
        table = s["table"]
        devices = s["devices"]
        readings = s["readings"]
        measurements = ", ".join(s["measurements"])
        if table in available_exports:
            export_ts = available_exports[table][:16].replace("T", " ")  # Date + time
            download_link = (
                f'<a href="/download/{table}" title="Download CSV">CSV</a> '
                f"<small>({export_ts})</small>"
            )
        else:
            download_link = "-"
        sensor_rows.append(
            f'<tr>'
            f'<td><a href="/table/{table}">{table}</a></td>'
            f'<td>{devices}</td>'
            f'<td>{readings:,}</td>'
            f'<td>{measurements}</td>'
            f'<td>{download_link}</td>'
            f'</tr>'
        )

    table_html = f"""
        <table>
            <thead>
                <tr>
                    <th>Sensor Type</th>
                    <th>Devices</th>
                    <th>Readings</th>
                    <th>Measurements</th>
                    <th>Download</th>
                </tr>
            </thead>
            <tbody>
                {''.join(sensor_rows)}
            </tbody>
        </table>
    """

    # Build measurement types section (hide items that are part of a group)
    grouped_measurements = set()
    for group_cols in MEASUREMENT_GROUPS.values():
        grouped_measurements.update(group_cols)

    measurement_rows = []
    for measurement, tables in sorted(MEASUREMENTS_TO_TABLES.items()):
        if measurement in grouped_measurements:
            continue  # Skip individual items that are shown as a group
        measurement_rows.append(
            f'<tr>'
            f'<td><a href="/measurement/{measurement}">{measurement}</a></td>'
            f'<td>{", ".join(sorted(tables))}</td>'
            f'</tr>'
        )

    measurement_html = f"""
        <table>
            <thead>
                <tr>
                    <th>Measurement</th>
                    <th>Available in Sensors</th>
                </tr>
            </thead>
            <tbody>
                {''.join(measurement_rows)}
            </tbody>
        </table>
    """

    extra_css = """
        .user-info { float: right; color: #666; font-size: 0.9em; }
    """

    content = f"""
        <div class="user-info">Logged in as: {user}</div>
        <h1>WP6 Red - Sensor Dashboard</h1>

        <article>
            <h2>Light Analysis (DLI)</h2>
            <p>Daily Light Integral analysis and optimization tools.</p>
            <a href="/dli" role="button">DLI Dashboard</a>
        </article>

        <article>
            <h2>Custom Compare</h2>
            <p>Create a custom dual-axis chart
            by selecting two sensor/measurement combinations.</p>
            <a href="/compare" role="button">Compare</a>
        </article>

        <article>
            <h2>Compare by Measurement Type</h2>
            <p>View all sensors measuring the same thing:</p>
            {measurement_html}
        </article>

        <article>
            <h2>Browse by Sensor Type</h2>
            {table_html}
            {deps._export_info_html(export_meta)}
        </article>
    """

    return render_page("WP6 Red - Sensor Dashboard", content, extra_css=extra_css)
