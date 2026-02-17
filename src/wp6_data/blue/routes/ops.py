"""Blue dashboard operations endpoints: health, metrics, sync-status."""

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

from wp6_data.blue import deps
from wp6_data.shared import render_page

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for k8s probes (doesn't hit Neo4j)."""
    return {"status": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus metrics endpoint for sync observability."""
    try:
        sync_metrics = deps.fetch_sync_metrics()
    except Exception:
        # Return empty metrics if Neo4j is unavailable
        return "# wp6_sync_up 0\n"

    lines = [
        "# HELP wp6_sync_last_run_timestamp_seconds Unix timestamp of last sync run",
        "# TYPE wp6_sync_last_run_timestamp_seconds gauge",
        "# HELP wp6_sync_last_run_success Whether the last sync succeeded (1=yes, 0=no)",
        "# TYPE wp6_sync_last_run_success gauge",
        "# HELP wp6_sync_last_run_duration_seconds Duration of the last sync run",
        "# TYPE wp6_sync_last_run_duration_seconds gauge",
        "# HELP wp6_sync_last_run_records Number of records synced in the last run",
        "# TYPE wp6_sync_last_run_records gauge",
        "# HELP wp6_sync_total_runs Total number of sync runs",
        "# TYPE wp6_sync_total_runs counter",
        "# HELP wp6_sync_total_failures Total number of failed sync runs",
        "# TYPE wp6_sync_total_failures counter",
        "# HELP wp6_sync_last_api_status HTTP status code of the last API error (0 if no error)",
        "# TYPE wp6_sync_last_api_status gauge",
        "# HELP wp6_sync_data_lag_seconds Seconds since the last successfully synced data point",
        "# TYPE wp6_sync_data_lag_seconds gauge",
    ]

    now = datetime.now().timestamp()

    for m in sync_metrics:
        endpoint = m.get("endpoint", "unknown")
        labels = f'endpoint="{endpoint}"'

        if m.get("last_run_at"):
            ts = m["last_run_at"].timestamp()
            lines.append(f"wp6_sync_last_run_timestamp_seconds{{{labels}}} {ts:.0f}")

        success = 1 if m.get("last_run_success") else 0
        lines.append(f"wp6_sync_last_run_success{{{labels}}} {success}")

        if m.get("duration_seconds") is not None:
            dur = m["duration_seconds"]
            lines.append(f"wp6_sync_last_run_duration_seconds{{{labels}}} {dur:.2f}")

        records = m.get("records") or 0
        lines.append(f"wp6_sync_last_run_records{{{labels}}} {records}")

        total_runs = m.get("total_runs") or 0
        lines.append(f"wp6_sync_total_runs{{{labels}}} {total_runs}")

        total_failures = m.get("total_failures") or 0
        lines.append(f"wp6_sync_total_failures{{{labels}}} {total_failures}")

        api_status = m.get("api_status") or 0
        lines.append(f"wp6_sync_last_api_status{{{labels}}} {api_status}")

        if m.get("last_data_timestamp"):
            lag = now - m["last_data_timestamp"].timestamp()
            lines.append(f"wp6_sync_data_lag_seconds{{{labels}}} {lag:.0f}")

    return "\n".join(lines) + "\n"


@router.get("/sync-status", response_class=HTMLResponse)
async def sync_status() -> str:
    """Human-readable sync status page."""
    try:
        sync_metrics = deps.fetch_sync_metrics()
    except Exception as e:
        return render_page("Sync Status", f"<h1>Error fetching sync status</h1><pre>{e}</pre>")

    if not sync_metrics:
        return render_page("Sync Status", "<h1>No sync metadata found</h1>")

    rows = []
    for m in sync_metrics:
        endpoint = m.get("endpoint", "unknown")
        success = m.get("last_run_success")
        status_icon = "✅" if success else "❌"
        last_run = m.get("last_run_at")
        last_run_str = last_run.strftime("%Y-%m-%d %H:%M:%S UTC") if last_run else "Never"
        duration = m.get("duration_seconds")
        duration_str = f"{duration:.1f}s" if duration else "-"
        records = m.get("records") or 0
        error = m.get("error") or "-"
        api_status = m.get("api_status")
        api_detail = m.get("api_error_detail") or ""
        total_runs = m.get("total_runs") or 0
        total_failures = m.get("total_failures") or 0

        error_html = f"<code>{error}</code>"
        if api_status:
            error_html += f"<br><small>HTTP {api_status}</small>"
        if api_detail:
            # Truncate and escape for display
            detail_preview = api_detail[:200].replace("<", "&lt;").replace(">", "&gt;")
            error_html += (
                f"<br><small><pre style='white-space:pre-wrap;'>{detail_preview}...</pre></small>"
            )

        rows.append(f"""
            <tr>
                <td>{endpoint}</td>
                <td>{status_icon}</td>
                <td>{last_run_str}</td>
                <td>{duration_str}</td>
                <td>{records:,}</td>
                <td>{total_runs}</td>
                <td>{total_failures}</td>
                <td>{error_html}</td>
            </tr>
        """)

    table = f"""
        <table>
            <thead>
                <tr>
                    <th>Endpoint</th>
                    <th>Status</th>
                    <th>Last Run</th>
                    <th>Duration</th>
                    <th>Records</th>
                    <th>Total Runs</th>
                    <th>Failures</th>
                    <th>Last Error</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    """

    content = f"""
        <h1>Sync Status</h1>
        {table}
        <p><a href="/metrics">View Prometheus metrics</a></p>
    """

    return render_page("Sync Status - WP6 Blue", content, show_back_link=True)
