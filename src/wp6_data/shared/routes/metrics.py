"""Prometheus metrics endpoint for sync observability (no auth, for scrapes).

Exposes each endpoint in the twin's `sync_metadata`, plus the same health
verdict the /status page shows (`wp6_sync_state`), so an alert and the page
can never disagree about whether a feed is stale.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.routes.status import SYNC_STATES, classify_sync
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter()

# (name, type, help). Names predate this module; the Grafana wp6-blue-activity
# dashboard queries them, so they are kept as-is.
_METRICS = [
    ("wp6_sync_up", "gauge", "Whether sync metadata could be read (1=yes, 0=no)"),
    ("wp6_sync_last_run_timestamp_seconds", "gauge", "Unix timestamp of last sync run"),
    ("wp6_sync_last_run_success", "gauge", "Whether the last sync succeeded (1=yes, 0=no)"),
    ("wp6_sync_last_run_duration_seconds", "gauge", "Duration of the last sync run"),
    ("wp6_sync_last_run_records", "gauge", "Number of records synced in the last run"),
    ("wp6_sync_total_runs", "counter", "Total number of sync runs"),
    ("wp6_sync_total_failures", "counter", "Total number of failed sync runs"),
    ("wp6_sync_consecutive_failures", "gauge", "Failed runs in a row (0 after a success)"),
    ("wp6_sync_last_api_status", "gauge", "HTTP status code of the last API error (0 if none)"),
    ("wp6_sync_data_lag_seconds", "gauge", "Seconds since the last successfully synced data point"),
    ("wp6_sync_state", "gauge", "Status-page health verdict, one 0/1 series per state"),
]


def _labels(**kv: str) -> str:
    return ",".join(f'{k}="{v}"' for k, v in kv.items())


def render_metrics(twin_id: str, rows: list[dict[str, Any]] | None, now: datetime) -> str:
    """Prometheus text format for a twin's sync rows; `None` = metadata unreadable."""
    lines: list[str] = []
    for name, kind, help_text in _METRICS:
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]

    lines.append(f"wp6_sync_up{{{_labels(twin=twin_id)}}} {0 if rows is None else 1}")

    for m in rows or []:
        base = _labels(
            twin=twin_id,
            endpoint=m.get("endpoint", "unknown"),
            source_type=m.get("source_type", "synced"),
        )

        def emit(name: str, value: float, fmt: str = ".0f", base: str = base) -> None:
            lines.append(f"{name}{{{base}}} {value:{fmt}}")

        if m.get("last_run_at"):
            emit("wp6_sync_last_run_timestamp_seconds", m["last_run_at"].timestamp())
        emit("wp6_sync_last_run_success", 1 if m.get("last_run_success") else 0)
        if m.get("duration_seconds") is not None:
            emit("wp6_sync_last_run_duration_seconds", m["duration_seconds"], ".2f")
        emit("wp6_sync_last_run_records", m.get("records") or 0)
        emit("wp6_sync_total_runs", m.get("total_runs") or 0)
        emit("wp6_sync_total_failures", m.get("total_failures") or 0)
        emit("wp6_sync_consecutive_failures", m.get("consecutive_failures") or 0)
        emit("wp6_sync_last_api_status", m.get("api_status") or 0)
        if m.get("last_data_timestamp"):
            lag = now.timestamp() - m["last_data_timestamp"].timestamp()
            emit("wp6_sync_data_lag_seconds", lag)

        current, _, _ = classify_sync(m, now)
        for state in SYNC_STATES:
            lines.append(
                f"wp6_sync_state{{{base},state=\"{state}\"}} {1 if state == current else 0}"
            )

    return "\n".join(lines) + "\n"


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics(
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    config: Annotated[TwinConfig, Depends(get_twin_config)],
) -> str:
    try:
        rows = await provider.fetch_sync_metrics()
    except Exception:
        rows = None  # DB unreachable → wp6_sync_up 0, which the alert rules watch
    return render_metrics(config.twin_id, rows, datetime.now(UTC))
