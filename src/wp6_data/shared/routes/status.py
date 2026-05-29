"""Shared status page: sync metrics and data coverage timeline."""

import inspect
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from wp6_data.shared import (
    PRESENCE_NONE_COLOR,
    build_weekly_coverage,
    render_card,
    render_coverage_grid,
    render_page,
)
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter(dependencies=[Depends(verify_session_user)])

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
        width: 6px; height: 14px; border-radius: 2px;
        cursor: default; flex-shrink: 0;
    }
    .uptime-block:hover { opacity: 0.75; transform: scaleY(1.3); }
    .uptime-month-mark {
        width: 6px; flex-shrink: 0; text-align: left; position: relative;
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


async def _build_sync_table(provider: SensorDataProvider) -> str | None:
    """Build the sync status HTML table, or None if no data."""
    try:
        sync_metrics = await provider.fetch_sync_metrics()
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


def _coverage_legend(mode: str) -> str:
    """Legend swatches for a coverage scale."""
    if mode == "presence":
        items = [("#22c55e", "Measured"), (PRESENCE_NONE_COLOR, "No measurement")]
    else:
        items = [
            ("#22c55e", "Good (7 days)"),
            ("#eab308", "Partial (3-6 days)"),
            ("#ef4444", "Poor (0-2 days)"),
        ]
    swatches = "".join(
        f'<div class="uptime-legend-item">'
        f'<span class="uptime-legend-swatch" style="background:{color}"></span> {label}'
        f"</div>"
        for color, label in items
    )
    return f'<div class="uptime-legend">{swatches}</div>'


def _coverage_section(
    records: list[dict], *, mode: str, project_start
) -> str:
    """One coverage grid (summary + grid + legend) for a given scale."""
    weekly_df = build_weekly_coverage(records, project_start, mode=mode)
    grid_html = render_coverage_grid(weekly_df, mode=mode)

    good_pct = (
        len(weekly_df[weekly_df["status"] == "good"]) / len(weekly_df) * 100
        if len(weekly_df) > 0
        else 0
    )
    devices = {r["device"] for r in records}
    sensors = {(r["device"], r["sensor"]) for r in records}
    if mode == "presence":
        summary = (
            f"<p>{good_pct:.0f}% of weeks measured "
            f"across {len(devices)} devices and {len(sensors)} sensors.</p>"
        )
    else:
        summary = (
            f"<p>{good_pct:.0f}% good coverage "
            f"across {len(devices)} devices and {len(sensors)} sensors.</p>"
        )
    return summary + grid_html + _coverage_legend(mode)


async def _build_coverage_html(provider: SensorDataProvider) -> str:
    """Build the coverage timeline, split into automated-sensor and manual
    sections when the provider tags any record ``manual`` (else a single grid,
    unchanged — e.g. twins with no manual sources)."""
    records = await provider.fetch_daily_coverage()
    if not records:
        return "<p>No coverage data available.</p>"

    # Shared timeline start so both grids line up week-for-week.
    days = [r["day"] for r in records if r.get("day")]
    project_start = min(days) if days else None

    manual = [r for r in records if r.get("manual")]
    sensor = [r for r in records if not r.get("manual")]

    if not manual:
        return _coverage_section(sensor, mode="daily", project_start=project_start)

    parts: list[str] = []
    if sensor:
        parts.append("<h3>Sensor data</h3>")
        parts.append(
            _coverage_section(sensor, mode="daily", project_start=project_start)
        )
    parts.append("<h3>Manual data</h3>")
    parts.append(
        _coverage_section(manual, mode="presence", project_start=project_start)
    )
    return "\n".join(parts)


@router.get("/status", response_class=HTMLResponse)
async def status(
    request: Request,
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """Combined status page: sync status, data coverage, and twin extras."""
    sync_table = await _build_sync_table(provider)
    sync_html = sync_table if sync_table else "<p>No sync metadata available.</p>"

    coverage_html = await _build_coverage_html(provider)

    extras_parts: list[str] = []
    for extra_fn in config.status_extras:
        result = extra_fn(request)
        if inspect.isawaitable(result):
            result = await result
        if result:
            extras_parts.append(result)
    extras_html = "\n".join(extras_parts)

    content = f"""
        <h1>Status</h1>

        {render_card("Sync Status", sync_html)}

        {render_card("Data Coverage", coverage_html,
                      description="Each block is one week. From start of project to now.")}

        {extras_html}
    """

    return render_page(
        f"{config.title} - Status", content,
        show_back_link=True, extra_css=COVERAGE_CSS,
        data_source=provider.data_source_label,
    )
