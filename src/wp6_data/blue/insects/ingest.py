"""CLI ingest command for the blue insect-trap CSV.

Thin wrapper that builds blue's manual-ingest service and delegates the
validate→apply round-trip to the shared runner, so the CLI and the admin
upload UI share exactly one apply path. Works locally and against the
remote/prod blue TSDB — the connection comes from ``WP6_TSDB_URL`` (default:
the local docker blue DB), so pointing it at prod is purely an env change.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import structlog
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool

from wp6_data.blue.insects.service import build_insect_service
from wp6_data.config import Settings
from wp6_data.shared.manual_ingest import ApplyResult
from wp6_data.shared.manual_ingest.cli import run_ingest
from wp6_data.shared.upload_storage import UploadStorage

log = structlog.get_logger()


async def _run(path: Path) -> ApplyResult:
    settings = Settings()
    pool = AsyncConnectionPool(
        settings.tsdb_url, min_size=1, max_size=2, open=False,
    )
    await pool.open()
    try:
        storage = UploadStorage(
            base_dir=Path(settings.blue_upload_dir), pool=pool,
        )
        service = build_insect_service(pool, storage)
        return await run_ingest(service, path)
    finally:
        await pool.close()


def main() -> None:
    """Console-script entry point: `wp6-blue-ingest-insects <path-to-csv>`."""
    load_dotenv()
    if len(sys.argv) != 2:
        print(
            "usage: wp6-blue-ingest-insects <path-to-csv>", file=sys.stderr,
        )
        raise SystemExit(2)
    path = Path(sys.argv[1])
    result = asyncio.run(_run(path))
    log.info(
        "insect_ingest_complete",
        upload_id=result.upload_id,
        row_count=result.row_count,
        path=str(path),
    )
