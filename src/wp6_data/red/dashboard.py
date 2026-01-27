"""WP6 Red Dashboard - MySQL-backed sensor visualization with authentication."""

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from wp6_data.red.db import MEASUREMENT_GROUPS, MEASUREMENTS_TO_TABLES, MySQLConnection
from wp6_data.shared import make_dual_axis_chart, make_line_chart, render_page

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

    try:
        df = await db.get_readings_by_measurement(measurement, limit_per_table=limit)
    except Exception as e:
        return render_page(
            f"{measurement} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
        )

    if df.empty:
        return render_page(
            f"{measurement} - WP6 Red",
            "<h1>No data found</h1>",
            show_back_link=True,
        )

    tables = MEASUREMENTS_TO_TABLES[measurement]
    fig = make_line_chart(df, title=f"{measurement} - All Sensors ({', '.join(tables)})")
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color: #666; font-size: 0.9em;">{len(df):,} data points</p>'

    return render_page(
        f"{measurement} - WP6 Red",
        stats_html + chart_html,
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
) -> str:
    """Chart all devices for a sensor table."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    try:
        df = await db.get_readings(table, limit=limit)
    except ValueError as e:
        return render_page(
            f"{table} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    if df.empty:
        return render_page(
            f"{table} - WP6 Red",
            "<h1>No data found</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    fig = make_line_chart(df, title=f"{table} - All Devices")
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    stats_html = f'<p style="color: #666; font-size: 0.9em;">{len(df):,} data points</p>'

    return render_page(
        f"{table} - WP6 Red",
        stats_html + chart_html,
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
) -> str:
    """Chart a specific device."""
    if not db:
        return render_page("WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    try:
        df = await db.get_readings(table, device_id=device_id, limit=limit)
    except ValueError as e:
        return render_page(
            f"{device_id} - WP6 Red",
            f"<h1>Error: {e}</h1>",
            show_back_link=True,
            back_url=f"/table/{table}",
        )

    if df.empty:
        return render_page(
            f"{device_id} - WP6 Red",
            "<h1>No data found</h1>",
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
        stats_html + chart_html,
        show_logo=False,
        show_footer=False,
        show_back_link=True,
        back_url=f"/table/{table}",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
