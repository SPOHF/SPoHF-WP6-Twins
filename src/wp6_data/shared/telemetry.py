"""OpenTelemetry tracing bootstrap (twin-agnostic).

Vendor-neutral by construction: the exporter is configured *only* through the
standard ``OTEL_*`` environment variables, so the backend (a collector, Jaeger,
Tempo, Dash0, …) is a deployment concern and never appears in code. Swapping
backends is an endpoint change, not a code change.

Setup is a **no-op unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set**, so local dev,
tests, and any deployment that hasn't opted in pay nothing and emit no
connection-error noise. To enable, point that variable at an OTLP/HTTP receiver,
e.g. locally::

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    OTEL_SERVICE_NAME=wp6-grey \
        python -m wp6_data.grey.dashboard

Relevant standard variables (all read by the SDK, none re-implemented here):
``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_EXPORTER_OTLP_PROTOCOL``,
``OTEL_EXPORTER_OTLP_HEADERS``, ``OTEL_SERVICE_NAME``,
``OTEL_RESOURCE_ATTRIBUTES``.
"""

import os

import structlog

logger = structlog.get_logger()

# Presence of an OTLP endpoint is the single enable signal. No endpoint → tracing
# stays off and every hook below short-circuits to a no-op.
_ENABLE_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"

_initialised = False


def tracing_enabled() -> bool:
    """True once :func:`setup_telemetry` has configured a live exporter."""
    return _initialised


def setup_telemetry(default_service_name: str | None = None) -> None:
    """Configure global tracing and instrument client libraries. Idempotent.

    Does nothing when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset. ``default_service_name``
    seeds ``service.name`` only when ``OTEL_SERVICE_NAME`` is not already set in the
    environment, so a per-deployment override always wins.
    """
    global _initialised
    if _initialised or not os.environ.get(_ENABLE_ENV):
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create() already merges OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES;
    # we only supply a fallback name so the env var stays authoritative.
    attrs = {}
    if default_service_name and not os.environ.get("OTEL_SERVICE_NAME"):
        attrs["service.name"] = default_service_name

    provider = TracerProvider(resource=Resource.create(attrs))
    # BatchSpanProcessor flushes on the provider's atexit shutdown, which matters
    # for the short-lived CLI/CronJob processes (sync, export, ingest).
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    _instrument_libraries()
    _initialised = True
    logger.info(
        "otel_tracing_enabled",
        endpoint=os.environ[_ENABLE_ENV],
        service=attrs.get("service.name") or os.environ.get("OTEL_SERVICE_NAME"),
    )


def _instrument_libraries() -> None:
    """Patch the shared client libraries so their calls emit spans automatically.

    Global and one-time: covers every ``httpx`` client (SPoHF API, OpenMeteo, OIDC)
    and every ``psycopg`` connection (the TimescaleDB pool), wherever they are
    created. aiomysql (red's MySQL source) has no standard instrumentor and is
    handled separately with manual spans.
    """
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

    HTTPXClientInstrumentor().instrument()
    PsycopgInstrumentor().instrument()


# Health/readiness probes and the Prometheus scrape are high-frequency, zero-signal
# noise in traces. Excluded from server spans by default; override per-deployment with
# the standard OTEL_PYTHON_FASTAPI_EXCLUDED_URLS env var (comma-separated regexes).
_DEFAULT_EXCLUDED_URLS = "health,metrics"


def instrument_fastapi(app) -> None:
    """Add request spans to a FastAPI app. No-op when tracing is disabled.

    Skips probe/scrape URLs entirely, and drops the per-ASGI-event ``http send`` /
    ``http receive`` child spans — the parent server span already covers the request,
    so those are pure noise (two ``send`` spans per response: start + body).
    """
    if not _initialised:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=os.environ.get(
            "OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", _DEFAULT_EXCLUDED_URLS
        ),
        exclude_spans=["send", "receive"],
    )
