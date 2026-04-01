"""Blue dashboard operations endpoints: metrics, maintenance."""

from datetime import datetime
from types import ModuleType
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from wp6_data.blue import deps
from wp6_data.blue.datasource import GetActiveSource
from wp6_data.shared import render_card, render_page

router = APIRouter()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus metrics endpoint for sync observability."""
    try:
        sync_metrics = await deps.fetch_sync_metrics()
    except Exception:
        # Return empty metrics if DB is unavailable
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


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
    rebuilt: int | None = Query(default=None),
) -> str:
    """Hidden maintenance page for ops tools."""
    _source, source_name = active_source
    is_yookr = source_name == "yookr"

    rebuilt_msg = ""
    if rebuilt is not None:
        rebuilt_msg = (
            f'<p role="alert" style="color: var(--pico-ins-color);">'
            f"Coverage index rebuilt: {rebuilt:,} entries.</p>"
        )

    coverage_card = (
        render_card(
            "Coverage Index",
            "<p>Not available — direct API mode.</p>",
        )
        if is_yookr
        else render_card(
            "Coverage Index",
            '<form method="post" action="/rebuild-coverage">'
            '<button type="submit">Rebuild Coverage Index</button></form>',
            description="Rebuild daily_coverage table from all existing readings.",
        )
    )

    content = f"""
        <h1>Maintenance</h1>
        {rebuilt_msg}
        {coverage_card}
        {render_card(
            "Metrics",
            '<p><a href="/metrics">Prometheus metrics</a></p>',
        )}
    """

    return render_page(
        "SPoHF Blue - Maintenance", content,
        show_back_link=True, data_source=source_name,
    )


@router.post("/rebuild-coverage")
async def rebuild_coverage() -> RedirectResponse:
    """Rebuild daily_coverage table from existing readings."""
    from wp6_data.db import get_pool, rebuild_daily_coverage

    pool = get_pool()
    async with pool.connection() as conn:
        count = await rebuild_daily_coverage(conn)
        await conn.commit()
    return RedirectResponse(url=f"/maintenance?rebuilt={count}", status_code=303)
