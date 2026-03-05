"""Entry point for wp6-data sync job.

Runs the SPoHF API sync, and optionally the Yookr direct-API sync
when WP6_YOOKR_EMAIL / WP6_YOOKR_PASSWORD are configured.

Usage:
    uv run python -m wp6_data              # run all configured syncs
    uv run python -m wp6_data --yookr      # run only Yookr sync
    uv run python -m wp6_data --spohf      # run only SPoHF sync
"""

import asyncio
import logging
import sys
from typing import Any

import structlog

from wp6_data.config import Settings
from wp6_data.sync import SyncOrchestrator


def configure_logging(settings: Settings) -> None:
    """Configure structlog for JSON or console output."""
    processors: list[Any] = [
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

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _run_spohf_sync(settings: Settings, logger: Any) -> int:
    """Run the SPoHF API → TimescaleDB sync."""
    logger.info(
        "spohf_sync_starting",
        api_base_url=settings.api_base_url,
        endpoints=settings.endpoint_list,
        sync_mode=settings.sync_mode,
    )
    orchestrator = SyncOrchestrator(settings)
    stats = asyncio.run(orchestrator.run())

    if stats["errors"]:
        logger.warning("spohf_sync_completed_with_errors", errors=stats["errors"])
        return 1

    logger.info(
        "spohf_sync_success",
        total_records=stats["total_records"],
        duration_seconds=round(stats["duration_seconds"], 2),
    )
    return 0


def _run_yookr_sync(settings: Settings, logger: Any) -> int:
    """Run the Yookr API → TimescaleDB sync."""
    from wp6_data.sync.yookr_orchestrator import YookrSyncOrchestrator

    logger.info(
        "yookr_sync_starting",
        yookr_base_url=settings.yookr_base_url,
        sync_mode=settings.sync_mode,
    )
    orchestrator = YookrSyncOrchestrator(settings)
    stats = asyncio.run(orchestrator.run())

    if stats["errors"]:
        logger.warning("yookr_sync_completed_with_errors", errors=stats["errors"])
        return 1

    logger.info(
        "yookr_sync_success",
        total_records=stats["total_records"],
        total_created=stats["total_created"],
        sensors_synced=stats["sensors_synced"],
        duration_seconds=round(stats.get("duration_seconds", 0), 2),
    )
    return 0


def main() -> int:
    """Main entry point for sync job."""
    settings = Settings()
    configure_logging(settings)
    logger = structlog.get_logger()

    args = sys.argv[1:]
    run_spohf = "--spohf" in args or not args
    run_yookr = "--yookr" in args or not args

    yookr_configured = bool(settings.yookr_email and settings.yookr_password)

    logger.info(
        "sync_job_starting",
        tsdb_url=settings.tsdb_url.split("@")[-1],  # hide credentials
        sync_mode=settings.sync_mode,
        run_spohf=run_spohf,
        run_yookr=run_yookr and yookr_configured,
    )

    exit_code = 0

    try:
        if run_spohf:
            exit_code |= _run_spohf_sync(settings, logger)

        if run_yookr and yookr_configured:
            exit_code |= _run_yookr_sync(settings, logger)
        elif run_yookr and not yookr_configured:
            logger.info("yookr_sync_skipped", reason="WP6_YOOKR_EMAIL/PASSWORD not set")

    except Exception as e:
        logger.exception("sync_job_failed", error=str(e))
        return 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
