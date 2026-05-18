"""CLI ingest command for the Sijia (Neurath) seed Excel file.

Thin wrapper that delegates to the shared manual-ingest service + runner so
the CLI and the admin upload UI share one apply path. ``ingest_sijia_file``
is the shared :func:`run_ingest` (kept under this name so existing callers
and tests are unaffected).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import structlog
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool

from wp6_data.config import RedSettings
from wp6_data.red.sijia.service import ApplyResult, ManualIngestService
from wp6_data.shared.manual_ingest.cli import run_ingest as ingest_sijia_file
from wp6_data.shared.upload_storage import UploadStorage

__all__ = ["ApplyResult", "ingest_sijia_file", "main"]

log = structlog.get_logger()


async def _run(path: Path) -> ApplyResult:
    settings = RedSettings()
    pool = AsyncConnectionPool(settings.tsdb_url, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        storage = UploadStorage(base_dir=Path(settings.upload_dir), pool=pool)
        service = ManualIngestService(pool=pool, storage=storage)
        return await ingest_sijia_file(service, path)
    finally:
        await pool.close()


def main() -> None:
    """Console-script entry point: `wp6-red-ingest-sijia <path-to-xlsx>`."""
    load_dotenv()
    if len(sys.argv) != 2:
        print("usage: wp6-red-ingest-sijia <path-to-xlsx>", file=sys.stderr)
        raise SystemExit(2)
    path = Path(sys.argv[1])
    result = asyncio.run(_run(path))
    log.info(
        "sijia_ingest_complete",
        upload_id=result.upload_id,
        row_count=result.row_count,
        path=str(path),
    )
