"""Shared status page: sync metrics and data coverage timeline."""

import html
import inspect
from datetime import UTC, datetime
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
from wp6_data.shared.templates.components import _format_timestamp_cell
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter(dependencies=[Depends(verify_session_user)])

SYNC_CSS = """
    .sync-endpoint { margin-bottom: 1rem; }
    .sync-endpoint:last-child { margin-bottom: 0; }
    .sync-head {
        display: flex; align-items: center; justify-content: space-between;
        gap: 0.5rem; margin-bottom: 0.6rem;
    }
    .sync-head strong { font-size: 1.05rem; }
    .sync-name { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
    .sync-type {
        font-size: 0.72rem; color: var(--pico-muted-color);
        border: 1px solid var(--pico-muted-border-color); border-radius: 999px;
        padding: 1px 8px; white-space: nowrap;
    }
    .sync-badge {
        font-size: 0.8rem; font-weight: 600; padding: 2px 10px; border-radius: 999px;
        white-space: nowrap; border: 1px solid transparent;
    }
    .sync-badge.success { background: #dcfce7; color: #166534; border-color: #86efac; }
    .sync-badge.warning { background: #fef9c3; color: #854d0e; border-color: #fde047; }
    .sync-badge.danger  { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
    .sync-badge.muted   { background: var(--pico-code-background-color);
        color: var(--pico-muted-color); }
    .sync-metrics {
        display: flex; flex-wrap: wrap; gap: 0.15rem 1.1rem;
        font-size: 0.85rem; color: var(--pico-muted-color);
    }
    .sync-metrics b { color: var(--pico-color); font-weight: 600; }
    .sync-metrics .fresh.warn b { color: #a16207; }
    .sync-metrics .fresh.bad b  { color: #b91c1c; }
    @media (prefers-color-scheme: dark) {
        .sync-metrics .fresh.warn b { color: #fde047; }
        .sync-metrics .fresh.bad b  { color: #fca5a5; }
    }
    .sync-reason {
        margin: 0.5rem 0 0; padding: 0.5rem 0.75rem; border-radius: 6px;
        font-size: 0.9rem; border-left: 3px solid transparent;
    }
    .sync-reason.warning { background: #fef9c3; border-left-color: #eab308; color: #854d0e; }
    .sync-reason.danger  { background: #fee2e2; border-left-color: #ef4444; color: #991b1b; }
    .sync-reason.success { background: #dcfce7; border-left-color: #22c55e; color: #166534; }
    .sync-spark { font-family: ui-monospace, monospace; letter-spacing: 1px; font-size: 1rem; }
    .sync-details { margin-top: 0.6rem; }
    .sync-details summary { cursor: pointer; font-size: 0.85rem; color: var(--pico-muted-color); }
    .sync-details table { margin: 0.5rem 0 0; font-size: 0.85rem; }
    .sync-details td:first-child { color: var(--pico-muted-color); white-space: nowrap; width: 1%; }
    @media (prefers-color-scheme: dark) {
        .sync-badge.success, .sync-reason.success { background: #14532d33; color: #86efac; }
        .sync-badge.warning, .sync-reason.warning { background: #713f1233; color: #fde047; }
        .sync-badge.danger,  .sync-reason.danger  { background: #7f1d1d33; color: #fca5a5; }
    }
"""

_SPARK_TICKS = "▁▂▃▄▅▆▇█"

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


def _rel(dt: datetime | None) -> str:
    """Relative-time span with an absolute-UTC tooltip ('—' when None)."""
    return _format_timestamp_cell(dt)[0]


def _lag_phrase(seconds: float) -> str:
    """Human data-lag, e.g. '10 h behind' / '35 min behind'."""
    if seconds >= 86400:
        return f"{int(seconds // 86400)} d behind"
    if seconds >= 3600:
        return f"{seconds / 3600:.0f} h behind"
    return f"{int(seconds // 60)} min behind"


# Source type → (chip icon, chip label). Selects which health dimensions apply:
# synced (scheduled ingest: freshness budget + run-SLA), manual (event-driven
# uploads: recency, no SLA/outage), live (queried, not synced — added later).
_SOURCE_TYPES = {
    "synced": ("🔄", "Synced"),
    "manual": ("✋", "Manual"),
    "live": ("📡", "Live"),
}


def _classify(m: dict, now: datetime) -> tuple[str, str, str]:
    """Return (state, label, tone) for a sync-metric row.

    `tone` is a CSS class (success / warning / danger / muted). A **synced**
    endpoint that succeeds but whose data lags past its freshness budget is
    'stale'/'outage' (upstream), distinct from 'failing' (the sync errored).
    **Manual** sources are event-driven, so they never go stale — only their
    last upload's success matters.
    """
    if not m.get("last_run_at"):
        return ("never", "Never run", "muted")
    if not m.get("last_run_success"):
        return ("failing", "Failing", "danger")

    if m.get("source_type") == "manual":
        return ("ok", "Up to date", "success")

    budget = m.get("freshness_budget")
    last_data = m.get("last_data_timestamp")
    if budget and last_data:
        lag_h = (now - last_data).total_seconds() / 3600
        stale_h, outage_h = budget
        if lag_h >= outage_h:
            return ("outage", "Likely outage", "danger")
        if lag_h >= stale_h:
            return ("stale", "Data stale", "warning")
    return ("healthy", "Healthy", "success")


def _sparkline(values: list) -> str:
    """Render most-recent-first record counts as an oldest→newest block spark."""
    nums = [int(v) for v in (values or []) if v is not None]
    if not nums:
        return ""
    hi = max(nums) or 1
    ticks = "".join(
        _SPARK_TICKS[min(len(_SPARK_TICKS) - 1, round(n / hi * (len(_SPARK_TICKS) - 1)))]
        for n in reversed(nums)  # stored newest-first; show chronologically
    )
    return f'<span class="sync-spark" title="last {len(nums)} runs, oldest→newest">{ticks}</span>'


def _detail_row(label: str, value: str) -> str:
    return f"<tr><td>{label}</td><td>{value}</td></tr>"


def _failing_reason(m: dict) -> str:
    """The shared 'Failing since …' banner (any source type)."""
    since = _rel(m.get("failing_since"))
    streak = m.get("consecutive_failures") or 0
    err = html.escape(str(m.get("error") or "unknown error"))
    api = m.get("api_status")
    api_txt = f" (HTTP {api})" if api else ""
    return (
        f'<p class="sync-reason danger">✖ <strong>Failing since {since}</strong> '
        f'— {streak} run(s) in a row. Last error: <code>{err}</code>{api_txt}</p>'
    )


def _render_synced(m: dict, now: datetime, state: str, tone: str) -> tuple[str, str, list[str]]:
    """Metrics line, reason banner, detail rows for a *synced* source."""
    last_data = m.get("last_data_timestamp")
    last_run = m.get("last_run_at")
    fresh_val, fresh_cls = _rel(last_data or last_run), ""
    if state in ("stale", "outage") and last_data:
        fresh_val = _lag_phrase((now - last_data).total_seconds())
        fresh_cls = " warn" if state == "stale" else " bad"
    fresh_label = "data" if m.get("freshness_budget") else "activity"

    runs_7d, ok_7d = m.get("runs_7d") or 0, m.get("ok_7d") or 0
    sla = f"<b>{100 * ok_7d / runs_7d:.1f}%</b> ({ok_7d}/{runs_7d})" if runs_7d else "<b>—</b>"
    records = m.get("records") or 0
    metrics = (
        '<div class="sync-metrics">'
        f'<span class="fresh{fresh_cls}"><b>{fresh_val}</b> {fresh_label}</span>'
        f'<span>SLA (7d) {sla}</span>'
        f'<span>last run <b>{_rel(last_run)}</b> · {records:,} rec</span>'
        '</div>'
    )

    reason = ""
    if state == "failing":
        reason = _failing_reason(m)
    elif state in ("stale", "outage") and last_data:
        lag = _lag_phrase((now - last_data).total_seconds())
        head = "Likely upstream outage" if state == "outage" else "Data is stale"
        reason = (
            f'<p class="sync-reason {tone}">⚠ <strong>{head}</strong> — no new data for '
            f'{lag}, but the sync itself is succeeding, so this points upstream '
            f'(the relay/source), not our pipeline.</p>'
        )

    recent = m.get("recent_success") or []
    x_of_y = f"{sum(1 for s in recent if s)} of last {len(recent)} OK" if recent else "—"
    rows = [
        _detail_row("Newest data point", _rel(last_data) if last_data else "—"),
        _detail_row("Recent outcomes", x_of_y),
        _detail_row("Records / run", _sparkline(m.get("recent_records")) or "—"),
    ]
    return metrics, reason, rows


def _render_manual(m: dict) -> tuple[str, str, list[str]]:
    """Metrics line, reason banner, detail rows for a *manual* upload source.

    Event-driven: recency of the last upload, no SLA or freshness/outage.
    """
    last_up = m.get("last_run_at") or m.get("last_data_timestamp")
    records = m.get("records") or 0
    metrics = (
        '<div class="sync-metrics">'
        f'<span>last upload <b>{_rel(last_up)}</b></span>'
        f'<span><b>{records:,}</b> rows</span>'
        '</div>'
    )
    reason = _failing_reason(m) if not m.get("last_run_success") and m.get("last_run_at") else ""
    rows = [
        _detail_row("Newest data point", _rel(m.get("last_data_timestamp"))),
        _detail_row("Uploads recorded", str(m.get("total_runs") or 0)),
    ]
    return metrics, reason, rows


def _build_sync_endpoint(m: dict, now: datetime) -> str:
    """Render one source's health card, shaped by its `source_type`."""
    endpoint = html.escape(str(m.get("endpoint", "unknown")))
    stype = m.get("source_type", "synced")
    state, label, tone = _classify(m, now)

    if stype == "manual":
        metrics, reason, detail_rows = _render_manual(m)
    else:  # "synced" (and, later, "live")
        metrics, reason, detail_rows = _render_synced(m, now, state, tone)

    detail_rows.append(
        _detail_row(
            "Lifetime",
            f"{m.get('total_runs') or 0} runs · {m.get('total_failures') or 0} failures",
        )
    )
    api_detail = m.get("api_error_detail")
    if state == "failing" and api_detail:
        preview = html.escape(api_detail[:400])
        pre = f"<pre style='white-space:pre-wrap;margin:0'>{preview}</pre>"
        detail_rows.append(_detail_row("Error detail", pre))
    details = (
        '<details class="sync-details"><summary>Details</summary>'
        f'<table>{"".join(detail_rows)}</table></details>'
    )

    icon, type_label = _SOURCE_TYPES.get(stype, _SOURCE_TYPES["synced"])
    return (
        '<article class="sync-endpoint">'
        '<div class="sync-head">'
        f'<span class="sync-name"><strong>{endpoint}</strong>'
        f'<span class="sync-type">{icon} {type_label}</span></span>'
        f'<span class="sync-badge {tone}">{label}</span></div>'
        f'{metrics}{reason}{details}</article>'
    )


async def _build_sync_table(provider: SensorDataProvider) -> str | None:
    """Build the sync-status cards, or None if no data."""
    try:
        sync_metrics = await provider.fetch_sync_metrics()
    except Exception:
        return None
    if not sync_metrics:
        return None

    now = datetime.now(UTC)
    return "".join(_build_sync_endpoint(m, now) for m in sync_metrics)


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
        show_back_link=True, extra_css=SYNC_CSS + COVERAGE_CSS,
    )
