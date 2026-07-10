"""E2E: ingest the seed Sijia Excel file into the real wp6_red TSDB.

Smoke-tests the full transactional flow end-to-end:
  - manual_uploads audit row is written (with hash, filename, row_count)
  - readings are bulk-inserted with source='sijia' and upload_id linkage
  - re-ingest is safe: replaces sijia rows, writes a new audit row
"""

from pathlib import Path

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN
from wp6_data.red.sijia.ingest import ingest_sijia_file
from wp6_data.red.sijia.service import ManualIngestService
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.shared.upload_storage import UploadStorage

pytestmark = pytest.mark.e2e

SEED_PATH = Path(__file__).parent.parent / "fixtures" / "sijia_seed.xlsx"


async def _purge_sijia(conn) -> None:
    """Strip out anything left over from a prior run so each test starts clean."""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM readings WHERE source = 'sijia'")
        await cur.execute("DELETE FROM manual_uploads WHERE source = 'sijia'")
    await conn.commit()


@pytest_asyncio.fixture()
async def red_pool(red_tsdb_conn):
    pool = AsyncConnectionPool(RED_TSDB_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    await ensure_schema_red(pool)
    await _purge_sijia(red_tsdb_conn)
    try:
        yield pool
    finally:
        await pool.close()
        await _purge_sijia(red_tsdb_conn)


@pytest.fixture()
def service(red_pool, tmp_path):
    storage = UploadStorage(base_dir=tmp_path, pool=red_pool)
    return ManualIngestService(pool=red_pool, storage=storage)


async def test_ingest_writes_audit_row_and_readings(service, red_tsdb_conn):
    result = await ingest_sijia_file(service, SEED_PATH)

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT source, filename, file_hash, row_count, error "
            "FROM manual_uploads WHERE id = %s",
            (result.upload_id,),
        )
        audit = await cur.fetchone()
        await cur.execute(
            "SELECT count(*) AS n FROM readings WHERE upload_id = %s",
            (result.upload_id,),
        )
        readings_count = (await cur.fetchone())["n"]

    assert audit["source"] == "sijia"
    assert audit["filename"] == "sijia_seed.xlsx"
    assert audit["error"] is None
    assert audit["row_count"] == result.row_count
    assert readings_count == result.row_count
    assert readings_count > 0


async def test_re_ingest_replaces_sijia_rows_and_writes_new_audit_row(
    service, red_tsdb_conn,
):
    first = await ingest_sijia_file(service, SEED_PATH)
    second = await ingest_sijia_file(service, SEED_PATH)

    assert second.upload_id != first.upload_id

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        # Old sijia rows are gone — only the second ingest's rows remain.
        await cur.execute(
            "SELECT count(*) AS n FROM readings WHERE upload_id = %s",
            (first.upload_id,),
        )
        assert (await cur.fetchone())["n"] == 0

        await cur.execute(
            "SELECT count(*) AS n FROM readings WHERE upload_id = %s",
            (second.upload_id,),
        )
        assert (await cur.fetchone())["n"] == second.row_count

        # Both audit rows are preserved (history).
        await cur.execute(
            "SELECT count(*) AS n FROM manual_uploads WHERE source = 'sijia'",
        )
        assert (await cur.fetchone())["n"] == 2


async def test_ingest_populates_coverage_days(service, red_tsdb_conn):
    """The post-apply cagg refresh gives /status per-day coverage for sijia rows."""
    await ingest_sijia_file(service, SEED_PATH)

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(DISTINCT (device_name, sensor_tag, bucket::date)) AS n "
            "FROM sensors_daily_summary WHERE source = 'sijia'"
        )
        coverage_days = (await cur.fetchone())["n"]

    assert coverage_days > 0


async def test_ingest_refreshes_cagg(service, red_tsdb_conn):
    """sensors_daily_summary reflects the ingested rows after refresh."""
    result = await ingest_sijia_file(service, SEED_PATH)

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT sum(reading_count) AS total "
            "FROM sensors_daily_summary WHERE source = 'sijia'"
        )
        row = await cur.fetchone()

    assert row["total"] == result.row_count


async def test_ingest_writes_sync_metadata_row(service, red_tsdb_conn):
    """A `sijia` row in sync_metadata is what makes the status page light up."""
    result = await ingest_sijia_file(service, SEED_PATH)

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT last_run_success, last_run_records, last_timestamp, total_runs "
            "FROM sync_metadata WHERE endpoint = 'sijia'"
        )
        row = await cur.fetchone()

    assert row is not None
    assert row["last_run_success"] is True
    assert row["last_run_records"] == result.row_count
    assert row["last_timestamp"] is not None
    assert row["total_runs"] >= 1
