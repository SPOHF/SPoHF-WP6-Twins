"""Entry point for wp6-data sync job."""

import asyncio
import logging
import sys

import structlog

from wp6_data.config import Settings
from wp6_data.sync import SyncOrchestrator


def configure_logging(settings: Settings) -> None:
    """Configure structlog for JSON or console output."""
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # Get log level from Python's logging module
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> int:
    """Main entry point for sync job."""
    try:
        settings = Settings()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        print("Required environment variables: WP6_API_TOKEN, WP6_NEO4J_URI, WP6_NEO4J_PASSWORD")
        return 1

    configure_logging(settings)
    logger = structlog.get_logger()

    # Log startup (without secrets)
    logger.info(
        "sync_job_starting",
        api_base_url=settings.api_base_url,
        neo4j_host=settings.neo4j_uri.split("://")[-1].split(":")[0],
        endpoints=settings.endpoint_list,
        lookback_hours=settings.sync_lookback_hours,
    )

    try:
        orchestrator = SyncOrchestrator(settings)
        stats = asyncio.run(orchestrator.run())

        if stats["errors"]:
            logger.warning("sync_completed_with_errors", errors=stats["errors"])
            return 1

        logger.info(
            "sync_job_success",
            total_records=stats["total_records"],
            duration_seconds=round(stats["duration_seconds"], 2),
        )
        return 0

    except Exception as e:
        logger.exception("sync_job_failed", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
