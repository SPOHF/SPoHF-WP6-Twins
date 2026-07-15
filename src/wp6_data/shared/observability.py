"""Unified observability bootstrap: structured logging + tracing, wired together.

One entry point (:func:`setup_observability`) that every process — dashboards and
CLI/CronJob scripts alike — calls once at startup. It configures structlog and
enables tracing, and crucially injects the active trace/span id into every log
line so logs (Loki) deep-link to traces (Dash0/Jaeger).
"""

from typing import Any

import structlog

from wp6_data.config import Settings
from wp6_data.shared.telemetry import setup_telemetry


def _add_trace_context(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: stamp the active trace/span id onto each log event.

    Resolved at log time, so it's a no-op when no span is current or tracing is
    disabled (the span context is then invalid and nothing is added).
    """
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(settings: Settings | None = None) -> None:
    """Configure structlog for JSON or console output, with trace correlation.

    ``log_level``/``log_format`` are app-wide (base ``Settings``), so callers that
    only hold a twin-specific settings object can omit the argument.
    """
    settings = settings or Settings()

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _add_trace_context,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    import logging

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_observability(service_name: str, settings: Settings | None = None) -> None:
    """Configure logging and enable tracing for one process. Call once at startup.

    ``service_name`` seeds ``service.name`` as a fallback (a per-deployment
    ``OTEL_SERVICE_NAME`` env var always wins).
    """
    configure_logging(settings)
    setup_telemetry(default_service_name=service_name)
