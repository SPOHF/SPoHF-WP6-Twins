"""WP6 Red Dashboard - MySQL-backed sensor visualization with authentication."""

import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from wp6_data.red.db import MEASUREMENT_GROUPS, MEASUREMENTS_TO_TABLES, MySQLConnection
from wp6_data.shared import (
    default_date_range,
    make_dual_axis_chart,
    make_line_chart,
    render_date_filter,
    render_page,
)

load_dotenv()

# MySQL connection settings
DB_HOST = os.getenv("WP6_RED_DB_HOST", "localhost")
DB_PORT = int(os.getenv("WP6_RED_DB_PORT", "3306"))
DB_NAME = os.getenv("WP6_RED_DB_NAME", "spohf2")
DB_USER = os.getenv("WP6_RED_DB_USER", "root")
DB_PASSWORD = os.getenv("WP6_RED_DB_PASSWORD", "")

# Auth users: "user1:pass1,user2:pass2" (required, no default)
AUTH_USERS_STR = os.getenv("WP6_RED_AUTH_USERS", "")


def parse_users(users_str: str) -> dict[str, str]:
    """Parse users from comma-separated string."""
    if not users_str:
        return {}
    users = {}
    for pair in users_str.split(","):
        if ":" in pair:
            username, password = pair.split(":", 1)
            users[username.strip()] = password.strip()
    return users


AUTH_USERS = parse_users(AUTH_USERS_STR)

# Database connection (managed via lifespan)
db: MySQLConnection | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle."""
    global db
    db = MySQLConnection(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    await db.connect()
    yield
    await db.close()


app = FastAPI(title="WP6 Red - Sensor Dashboard", lifespan=lifespan)
security = HTTPBasic()

# Serve static files
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if (PROJECT_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


def verify_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    """Verify Basic Auth credentials."""
    if not AUTH_USERS:
        raise HTTPException(
            status_code=500,
            detail="No users configured. Set WP6_RED_AUTH_USERS env var.",
        )

    if credentials.username not in AUTH_USERS:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    expected_password = AUTH_USERS[credentials.username]
    if not secrets.compare_digest(credentials.password.encode(), expected_password.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for k8s probes (no auth required)."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home(user: str = Depends(verify_auth)) -> str:
    """Dashboard home page - list available sensors."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>")

    sensors = await db.get_available_sensors()

    # Build sensor list HTML
    sensor_rows = []
    for s in sensors:
        table = s["table"]
        devices = s["devices"]
        readings = s["readings"]
        measurements = ", ".join(s["measurements"])
        sensor_rows.append(
            f'<tr>'
            f'<td><a href="/table/{table}">{table}</a></td>'
            f'<td>{devices}</td>'
            f'<td>{readings:,}</td>'
            f'<td>{measurements}</td>'
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
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #f5f5f5; }
        tr:hover { background-color: #f9f9f9; }
        .user-info { float: right; color: #666; font-size: 0.9em; }
        .section { margin-top: 40px; }
    """

    content = f"""
        <div class="user-info">Logged in as: {user}</div>
        <h1>WP6 Red - Sensor Dashboard</h1>

        <div class="section">
            <h2>Custom Compare</h2>
            <p><a href="/compare">Create a custom dual-axis chart</a>
            by selecting two sensor/measurement combinations.</p>
        </div>

        <div class="section">
            <h2>Compare by Measurement Type</h2>
            <p>View all sensors measuring the same thing:</p>
            {measurement_html}
        </div>

        <div class="section">
            <h2>Browse by Sensor Type</h2>
            {table_html}
        </div>
    """

    return render_page("WP6 Red - Sensor Dashboard", content, extra_css=extra_css)


@app.get("/measurement/{measurement}", response_class=HTMLResponse)
async def measurement_view(
    measurement: str,
    user: str = Depends(verify_auth),
    limit: int = Query(100000, description="Max records per sensor table"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Chart a measurement type across all sensors that have it."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    if measurement not in MEASUREMENTS_TO_TABLES:
        return render_page(
            f"{measurement} - WP6 Red",
            f"<h1>Unknown measurement: {measurement}</h1>",
            show_back_link=True,
        )

    default_start, default_end = default_date_range()
    start = start or default_start
    end = end or default_end
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    try:
        df = await db.get_readings_by_measurement(
            measurement, start=start_dt, end=end_dt, limit_per_table=limit,
        )
    except Exception as e:
        return render_page(
            f"{measurement} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
        )

    filter_html = render_date_filter(start, end)

    if df.empty:
        return render_page(
            f"{measurement} - WP6 Red",
            filter_html + "<h1>No data found</h1>",
            show_back_link=True,
        )

    tables = MEASUREMENTS_TO_TABLES[measurement]
    fig = make_line_chart(df, title=f"{measurement} - All Sensors ({', '.join(tables)})")
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color: #666; font-size: 0.9em;">{len(df):,} data points</p>'

    return render_page(
        f"{measurement} - WP6 Red",
        filter_html + stats_html + chart_html,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
    )


@app.get("/table/{table}", response_class=HTMLResponse)
async def table_view(table: str, user: str = Depends(verify_auth)) -> str:
    """Show devices for a sensor table."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    try:
        devices = await db.get_devices_for_table(table)
    except ValueError as e:
        return render_page(
            f"{table} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
        )

    device_list = "".join(
        f'<li><a href="/chart/{table}/{device}">{device}</a></li>' for device in devices
    )

    content = f"""
        <h1>{table}</h1>
        <h2>Devices</h2>
        <ul>{device_list}</ul>
        <h2>View All Devices</h2>
        <p><a href="/chart/{table}">Combined chart (all devices)</a></p>
    """

    return render_page(f"{table} - WP6 Red", content, show_back_link=True)


@app.get("/chart/{table}", response_class=HTMLResponse)
async def chart_all(
    table: str,
    user: str = Depends(verify_auth),
    limit: int = Query(50000, description="Max records to fetch"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Chart all devices for a sensor table."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    default_start, default_end = default_date_range()
    start = start or default_start
    end = end or default_end
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    try:
        df = await db.get_readings(table, start=start_dt, end=end_dt, limit=limit)
    except ValueError as e:
        return render_page(
            f"{table} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    filter_html = render_date_filter(start, end)

    if df.empty:
        return render_page(
            f"{table} - WP6 Red",
            filter_html + "<h1>No data found</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    fig = make_line_chart(df, title=f"{table} - All Devices")
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color: #666; font-size: 0.9em;">{len(df):,} data points</p>'

    return render_page(
        f"{table} - WP6 Red",
        filter_html + stats_html + chart_html,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
        back_url=f"/table/{table}",
    )


@app.get("/chart/{table}/{device_id}", response_class=HTMLResponse)
async def chart_device(
    table: str,
    device_id: str,
    user: str = Depends(verify_auth),
    limit: int = Query(50000, description="Max records to fetch"),
    start: Annotated[date | None, Query(description="Start date (default: 7 days ago)")] = None,
    end: Annotated[date | None, Query(description="End date (default: today)")] = None,
) -> str:
    """Chart a specific device."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    default_start, default_end = default_date_range()
    start = start or default_start
    end = end or default_end
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    try:
        df = await db.get_readings(
            table, device_id=device_id, start=start_dt, end=end_dt, limit=limit,
        )
    except ValueError as e:
        return render_page(
            f"{device_id} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    filter_html = render_date_filter(start, end)

    if df.empty:
        return render_page(
            f"{device_id} - WP6 Red",
            filter_html + "<h1>No data found</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    # Check if we can do dual axis (2 different measurements)
    sensors = df["sensor"].unique()
    if len(sensors) == 2:
        fig = make_dual_axis_chart(df, sensors[0], sensors[1], title=f"{table} - {device_id}")
    else:
        fig = make_line_chart(df, title=f"{table} - {device_id}")

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color: #666; font-size: 0.9em;">{len(df):,} data points</p>'

    return render_page(
        f"{device_id} - WP6 Red",
        filter_html + stats_html + chart_html,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
        back_url=f"/table/{table}",
    )


@app.get("/compare", response_class=HTMLResponse)
async def compare_form(user: str = Depends(verify_auth)) -> str:
    """Form to select two device/measurement pairs for a custom dual-axis chart."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    devices = await db.get_all_devices()
    # device_id -> list of measurements (for JS)
    device_data_json = json.dumps(
        {did: info["measurements"] for did, info in sorted(devices.items())}
    )
    device_ids = sorted(devices.keys())

    def select_html(prefix: str, label: str) -> str:
        device_options = "".join(
            f'<option value="{d}">{d}</option>' for d in device_ids
        )
        return f"""
        <fieldset style="border:1px solid #ccc; padding:16px; border-radius:6px;">
            <legend><strong>{label}</strong></legend>
            <label>Device
                <select name="{prefix}_device" id="{prefix}_device"
                        onchange="updateMeasurements('{prefix}')"
                        style="padding:4px;">
                    {device_options}
                </select>
            </label>
            <label style="margin-left:12px;">Measurement
                <select name="{prefix}_measurement" id="{prefix}_measurement"
                        style="padding:4px;">
                </select>
            </label>
        </fieldset>
        """

    extra_css = """
        fieldset { display: inline-block; margin-right: 16px; margin-bottom: 12px; }
    """

    content = f"""
        <h1>Custom Compare</h1>
        <p>Select two device/measurement combinations to plot on a dual y-axis chart.</p>
        <form method="get" action="/compare/chart">
            <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:16px;">
                {select_html("left", "Left Y-axis")}
                {select_html("right", "Right Y-axis")}
            </div>
            <button type="submit"
                    style="padding:8px 24px; background:#0066cc; color:white;
                           border:none; border-radius:4px; cursor:pointer; font-size:1em;">
                Generate Chart
            </button>
        </form>
        <script>
        var deviceData = {device_data_json};
        function updateMeasurements(prefix) {{
            var device = document.getElementById(prefix + '_device').value;
            var sel = document.getElementById(prefix + '_measurement');
            sel.innerHTML = '';
            (deviceData[device] || []).forEach(function(m) {{
                var opt = document.createElement('option');
                opt.value = m; opt.textContent = m;
                sel.appendChild(opt);
            }});
        }}
        updateMeasurements('left');
        updateMeasurements('right');
        </script>
    """

    return render_page("Custom Compare - WP6 Red", content, extra_css=extra_css,
                       show_back_link=True)


@app.get("/compare/chart", response_class=HTMLResponse)
async def compare_chart(
    left_device: str = Query(...),
    left_measurement: str = Query(...),
    right_device: str = Query(...),
    right_measurement: str = Query(...),
    user: str = Depends(verify_auth),
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Render a dual-axis chart for two user-selected device/measurement pairs."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    default_start, default_end = default_date_range()
    start = start or default_start
    end = end or default_end
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    try:
        left_df = await db.get_readings_for_comparison(
            left_device, left_measurement, start=start_dt, end=end_dt,
        )
        right_df = await db.get_readings_for_comparison(
            right_device, right_measurement, start=start_dt, end=end_dt,
        )
    except ValueError as e:
        return render_page(
            "Compare - WP6 Red", f"<h1>Error: {e}</h1>",
            show_back_link=True, back_url="/compare",
        )

    import pandas as pd

    df = pd.concat([left_df, right_df], ignore_index=True)

    filter_html = render_date_filter(start, end)

    if df.empty:
        return render_page(
            "Compare - WP6 Red", filter_html + "<h1>No data found</h1>",
            show_back_link=True, back_url="/compare",
        )

    left_label = f"{left_device} | {left_measurement}"
    right_label = f"{right_device} | {right_measurement}"

    # Relabel sensor column so dual axis chart can split on it
    df.loc[df["sensor"] == left_measurement, "sensor"] = left_label
    df.loc[df["sensor"] == right_measurement, "sensor"] = right_label

    fig = make_dual_axis_chart(df, left_label, right_label)
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color:#666; font-size:0.9em;">{len(df):,} data points</p>'

    return render_page(
        "Compare - WP6 Red",
        filter_html + stats_html + chart_html,
        show_logo=False, show_footer=False, show_back_link=True, back_url="/compare",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
