"""Blue dashboard operations endpoints: health, metrics, status."""

from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from wp6_data.blue import deps
from wp6_data.shared import (
    build_weekly_coverage,
    render_card,
    render_coverage_grid,
    render_page,
)

router = APIRouter()

COVERAGE_CSS = """
    .uptime-grid { display: flex; flex-direction: column; gap: 0; overflow-x: auto; }
    .uptime-grid details { margin: 0; }
    .uptime-grid summary { cursor: pointer; list-style: none; }
    .uptime-grid details[open] > summary { margin-bottom: 0; }
    .uptime-grid summary::-webkit-details-marker { display: none; }
    .uptime-row { display: flex; align-items: center; gap: 4px; min-height: 16px; }
    .uptime-header { margin-bottom: 2px; }
    .uptime-label {
        min-width: 200px; max-width: 200px; font-size: 0.75rem;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        line-height: 1.2;
    }
    .uptime-device { font-weight: bold; margin-top: 4px; }
    .uptime-sensor { padding-left: 12px; }
    .uptime-blocks { display: flex; gap: 1px; align-items: center; }
    .uptime-block {
        width: 8px; height: 14px; border-radius: 2px;
        cursor: default; flex-shrink: 0;
    }
    .uptime-block:hover { opacity: 0.75; transform: scaleY(1.3); }
    .uptime-month-mark {
        width: 8px; flex-shrink: 0; text-align: left; position: relative;
    }
    .uptime-month-mark span {
        font-size: 0.6rem; position: absolute; top: 0; left: 0;
        white-space: nowrap; color: var(--pico-muted-color);
    }
    .uptime-legend { display: flex; gap: 12px; margin-top: 10px; font-size: 0.8rem; }
    .uptime-legend-item { display: flex; align-items: center; gap: 4px; }
    .uptime-legend-swatch {
        width: 12px; height: 12px; border-radius: 2px; display: inline-block;
    }
"""


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


def _build_sync_table() -> str | None:
    """Build the sync status HTML table, or None if no data."""
    try:
        sync_metrics = deps.fetch_sync_metrics()
    except Exception:
        return None

    if not sync_metrics:
        return None

    rows = []
    for m in sync_metrics:
        endpoint = m.get("endpoint", "unknown")
        success = m.get("last_run_success")
        status_icon = "OK" if success else "FAIL"
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

    return f"""
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


def _build_coverage_html() -> str:
    """Build the coverage timeline HTML section."""
    records = deps.fetch_daily_coverage()
    if not records:
        return "<p>No coverage data. Run a sync or rebuild the coverage index.</p>"

    weekly_df = build_weekly_coverage(records)
    grid_html = render_coverage_grid(weekly_df)

    good_pct = (
        len(weekly_df[weekly_df["status"] == "good"]) / len(weekly_df) * 100
        if len(weekly_df) > 0
        else 0
    )

    legend_html = """
    <div class="uptime-legend">
        <div class="uptime-legend-item">
            <span class="uptime-legend-swatch" style="background:#22c55e"></span> Good (5-7 days)
        </div>
        <div class="uptime-legend-item">
            <span class="uptime-legend-swatch" style="background:#eab308"></span> Partial (1-4 days)
        </div>
        <div class="uptime-legend-item">
            <span class="uptime-legend-swatch" style="background:#ef4444"></span> No data
        </div>
    </div>
    """

    return f"<p>{good_pct:.0f}% good coverage.</p>" + grid_html + legend_html


@router.get("/status", response_class=HTMLResponse)
async def status() -> str:
    """Combined status page: sync status and data coverage."""
    # Sync status section
    sync_table = _build_sync_table()
    sync_html = sync_table if sync_table else "<p>No sync metadata found.</p>"

    # Coverage section
    coverage_html = _build_coverage_html()

    content = f"""
        <h1>Status</h1>

        {render_card("Sync Status", sync_html)}

        {render_card("Data Coverage", coverage_html,
                      description="Each block is one week. From start of project to now.")}
    """

    return render_page("Status - WP6 Blue", content, show_back_link=True, extra_css=COVERAGE_CSS)


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance(rebuilt: int | None = Query(default=None)) -> str:
    """Hidden maintenance page for ops tools."""
    rebuilt_msg = ""
    if rebuilt is not None:
        rebuilt_msg = (
            f'<p role="alert" style="color: var(--pico-ins-color);">'
            f"Coverage index rebuilt: {rebuilt:,} entries.</p>"
        )

    content = f"""
        <h1>Maintenance</h1>
        {rebuilt_msg}
        {render_card(
            "Coverage Index",
            '<form method="post" action="/rebuild-coverage">'
            '<button type="submit">Rebuild Coverage Index</button></form>',
            description="Rebuild DailyCoverage nodes from all existing Readings.",
        )}
        {render_card(
            "Metrics",
            '<p><a href="/metrics">Prometheus metrics</a></p>',
        )}
    """

    return render_page("Maintenance - WP6 Blue", content, show_back_link=True)


@router.post("/rebuild-coverage")
async def rebuild_coverage() -> RedirectResponse:
    """Rebuild all DailyCoverage nodes from existing Readings."""
    with deps._driver.session() as session:
        result = session.run(
            "MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)-[:RECORDED]->(r:Reading) "
            "WITH DISTINCT d.device_name AS dn, s.tag AS st, "
            "date(r.datetime_measure) AS day "
            "MERGE (c:DailyCoverage {device_name: dn, sensor_tag: st, day: day}) "
            "RETURN count(c) AS total"
        )
        record = result.single()
        count = record["total"] if record else 0
    return RedirectResponse(url=f"/maintenance?rebuilt={count}", status_code=303)
