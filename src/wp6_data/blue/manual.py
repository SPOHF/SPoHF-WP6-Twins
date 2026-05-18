"""Blue twin's manual-ingest glue — generic over blue manual sources.

Binds any blue :class:`ManualSource` to blue's cache invalidation and blue's
``Settings`` (TSDB URL + upload dir). Manual data is keyed by the ``source``
column on ``readings`` (distinct from the automated ``project`` view) — the
same as red. None of this is source-specific: adding a new blue manual
source is "write its decoder + descriptor module, add it to ``SOURCES``".
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

import structlog
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool

from wp6_data.blue.insects import INSECTS
from wp6_data.config import Settings
from wp6_data.db.pool import get_pool
from wp6_data.shared.manual_ingest import (
    ApplyResult,
    ManualIngestService,
    ManualSource,
    make_card,
    make_source_router,
    run_ingest,
)
from wp6_data.shared.upload_storage import UploadStorage

log = structlog.get_logger()

# Blue's manual sources. A new one = its decoder/descriptor module + an
# entry here; the rest of this module stays unchanged.
SOURCES: tuple[ManualSource, ...] = (INSECTS,)


def _invalidate_blue_caches() -> None:
    """Drop blue's cached sensor summaries after an apply.

    Blue's only cross-request cache is the shared sensor-summary TTLCache
    (keyed ``blue:*``); clearing it makes the next dashboard/home request
    see the just-applied rows instead of pre-upload stale data.
    """
    from wp6_data.shared.sensor_summary import invalidate

    invalidate()


def _build_service(
    source: ManualSource, pool: AsyncConnectionPool, storage: UploadStorage,
) -> ManualIngestService:
    return ManualIngestService(
        pool=pool,
        storage=storage,
        source=source,
        post_apply_hook=_invalidate_blue_caches,
    )


def _service_dependency(
    source: ManualSource,
) -> Callable[[], ManualIngestService]:
    """FastAPI dependency that builds the per-request service for ``source``."""

    def get_service() -> ManualIngestService:
        settings = Settings()
        storage = UploadStorage(
            base_dir=Path(settings.blue_upload_dir), pool=get_pool(),
        )
        return _build_service(source, get_pool(), storage)

    return get_service


def manual_routers() -> list:
    """Admin-gated upload routers for every blue manual source."""
    return [
        make_source_router(s, _service_dependency(s)) for s in SOURCES
    ]


def manual_cards() -> list[Callable]:
    """`/status` upload cards for every blue manual source."""
    return [make_card(s) for s in SOURCES]


async def _run(source: ManualSource, path: Path) -> ApplyResult:
    settings = Settings()
    pool = AsyncConnectionPool(
        settings.tsdb_url, min_size=1, max_size=2, open=False,
    )
    await pool.open()
    try:
        storage = UploadStorage(
            base_dir=Path(settings.blue_upload_dir), pool=pool,
        )
        return await run_ingest(_build_service(source, pool, storage), path)
    finally:
        await pool.close()


def _cli(source: ManualSource, usage: str) -> None:
    load_dotenv()
    if len(sys.argv) != 2:
        print(usage, file=sys.stderr)
        raise SystemExit(2)
    path = Path(sys.argv[1])
    result = asyncio.run(_run(source, path))
    log.info(
        "manual_ingest_complete",
        source=source.slug,
        upload_id=result.upload_id,
        row_count=result.row_count,
        path=str(path),
    )


def ingest_insects() -> None:
    """Console-script entry: `wp6-blue-ingest-insects <path-to-csv>`."""
    _cli(INSECTS, "usage: wp6-blue-ingest-insects <path-to-csv>")
