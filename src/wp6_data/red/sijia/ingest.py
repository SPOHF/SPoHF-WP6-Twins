"""CLI ingest pipeline for the Sijia (Neurath) seed Excel file.

Single-transaction flow:
  1. Parse + validate the Excel bytes → ValidationReport + Readings.
  2. Open one DB transaction:
       a. DELETE existing rows where source = 'sijia'  (re-ingest is safe).
       b. INSERT one manual_uploads audit row (RETURNING id).
       c. Bulk-insert all parsed Readings, tagging upload_id.
  3. Commit. Any failure rolls the whole transaction back.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from wp6_data.config import RedSettings
from wp6_data.red.sijia.parser import SOURCE, parse, validate

log = structlog.get_logger()


@dataclass(frozen=True)
class IngestResult:
    upload_id: int
    row_count: int


async def ingest_sijia_file(
    pool: AsyncConnectionPool, path: Path,
) -> IngestResult:
    """Ingest the Sijia Excel file at `path` into the red TSDB."""
    file_bytes = path.read_bytes()
    report = validate(file_bytes)
    readings = parse(file_bytes)

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "DELETE FROM readings WHERE source = %s", (SOURCE,),
            )
            await cur.execute(
                "INSERT INTO manual_uploads "
                "(source, filename, file_hash, row_count) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (SOURCE, path.name, report.file_hash, len(readings)),
            )
            row = await cur.fetchone()
            upload_id = row["id"]

            await cur.executemany(
                "INSERT INTO readings "
                "(time, device_name, sensor_tag, value, source, upload_id) "
                "VALUES (%(time)s, %(device_name)s, %(sensor_tag)s, "
                "        %(value)s, %(source)s, %(upload_id)s)",
                [
                    {
                        "time": r.time,
                        "device_name": r.device_name,
                        "sensor_tag": r.sensor_tag,
                        "value": r.value,
                        "source": r.source,
                        "upload_id": upload_id,
                    }
                    for r in readings
                ],
            )
        await conn.commit()

    return IngestResult(upload_id=upload_id, row_count=len(readings))


async def _run(path: Path) -> IngestResult:
    settings = RedSettings()
    pool = AsyncConnectionPool(settings.tsdb_url, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        return await ingest_sijia_file(pool, path)
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
