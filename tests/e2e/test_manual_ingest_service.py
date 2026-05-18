"""E2E tests for ManualIngestService (issue 009).

End-to-end coverage of the parser+storage+TSDB transactional apply path
that the admin upload UI delegates into. Runs against the real wp6_red
TSDB and a tmp_path PVC mount.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN
from wp6_data.red.sijia.parser import COLUMN_TO_SENSOR, EXPECTED_HEADERS, SHEET_NAME
from wp6_data.red.sijia.service import ManualIngestService
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.shared.upload_storage import UploadStorage

pytestmark = pytest.mark.e2e

SEED_PATH = Path(__file__).parent.parent / "fixtures" / "sijia_seed.xlsx"


def _tiny_sijia_xlsx(chlorophyll_value: float) -> bytes:
    """One-row valid sijia-format xlsx, varied by chlorophyll value.

    Used to produce distinct upload payloads (and therefore distinct
    file hashes) for tests that need ≥ 3 uploads to exercise the
    2-file prune policy.
    """
    headers = list(EXPECTED_HEADERS)
    row = [1, "TestVariety", "B", 2034, datetime(2025, 8, 7, 12, 0)] + [
        None
    ] * len(COLUMN_TO_SENSOR)
    # ChlM is the first sensor column after the meta columns.
    row[len(("Sample No.", "Variety", "Block", "Row", "Date"))] = chlorophyll_value

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(headers)
    ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _purge(conn) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM readings WHERE source = 'sijia'")
        await cur.execute("DELETE FROM manual_uploads WHERE source = 'sijia'")
    await conn.commit()


@pytest_asyncio.fixture()
async def red_pool(red_tsdb_conn):
    pool = AsyncConnectionPool(RED_TSDB_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    await ensure_schema_red(pool)
    await _purge(red_tsdb_conn)
    try:
        yield pool
    finally:
        await pool.close()
        await _purge(red_tsdb_conn)


@pytest.fixture()
def service(red_pool, tmp_path: Path) -> ManualIngestService:
    storage = UploadStorage(base_dir=tmp_path, pool=red_pool)
    return ManualIngestService(pool=red_pool, storage=storage)


async def test_apply_fresh_inserts_audit_row_and_readings(
    service: ManualIngestService, red_tsdb_conn,
):
    file_bytes = SEED_PATH.read_bytes()

    report = await service.validate(file_bytes)
    result = await service.apply(report.file_hash, filename="seed.xlsx")

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT source, file_hash, row_count, file_path, file_pruned, error "
            "FROM manual_uploads WHERE id = %s",
            (result.upload_id,),
        )
        audit = await cur.fetchone()
        await cur.execute(
            "SELECT COUNT(*) AS n FROM readings WHERE upload_id = %s",
            (result.upload_id,),
        )
        readings_count = (await cur.fetchone())["n"]

    assert audit["source"] == "sijia"
    assert audit["file_hash"] == report.file_hash
    assert audit["error"] is None
    assert audit["file_pruned"] is False
    assert audit["row_count"] == result.row_count
    assert readings_count == result.row_count
    assert readings_count > 0


async def test_re_apply_atomically_replaces_prior_data(
    service: ManualIngestService, red_tsdb_conn,
):
    """Second apply DELETEs prior sijia rows and INSERTs new ones in one txn.

    Both audit rows survive (history). All readings are linked to the
    second upload only — no readings remain referencing the first.
    """
    file_bytes = SEED_PATH.read_bytes()
    report = await service.validate(file_bytes)

    first = await service.apply(report.file_hash, filename="seed.xlsx")
    second = await service.apply(report.file_hash, filename="seed.xlsx")

    assert second.upload_id != first.upload_id

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT COUNT(*) AS n FROM readings WHERE upload_id = %s",
            (first.upload_id,),
        )
        assert (await cur.fetchone())["n"] == 0

        await cur.execute(
            "SELECT COUNT(*) AS n FROM readings WHERE upload_id = %s",
            (second.upload_id,),
        )
        assert (await cur.fetchone())["n"] == second.row_count

        await cur.execute(
            "SELECT COUNT(*) AS n FROM manual_uploads WHERE source = 'sijia'",
        )
        assert (await cur.fetchone())["n"] == 2


async def test_apply_after_third_upload_prunes_oldest_file_but_keeps_audit_rows(
    service: ManualIngestService, red_tsdb_conn, tmp_path: Path,
):
    """Three distinct uploads → only the latest 2 files survive on disk,
    but all 3 audit rows survive in DB; oldest's row is marked pruned."""
    payloads = [_tiny_sijia_xlsx(v) for v in (10.0, 20.0, 30.0)]
    hashes: list[str] = []
    for payload in payloads:
        report = await service.validate(payload)
        await service.apply(report.file_hash, filename="seed.xlsx")
        hashes.append(report.file_hash)

    # Disk: latest 2 of 3 files survive.
    sijia_dir = tmp_path / "sijia"
    surviving = {p.stem for p in sijia_dir.iterdir()}
    assert hashes[0] not in surviving, "oldest hash file must be pruned"
    assert hashes[1] in surviving
    assert hashes[2] in surviving

    # DB: all 3 audit rows preserved; oldest is marked pruned.
    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT file_hash, file_path, file_pruned "
            "FROM manual_uploads WHERE source = 'sijia' "
            "ORDER BY uploaded_at",
        )
        rows = await cur.fetchall()

    assert len(rows) == 3
    by_hash = {r["file_hash"]: r for r in rows}
    assert by_hash[hashes[0]]["file_pruned"] is True
    assert by_hash[hashes[0]]["file_path"] is None
    assert by_hash[hashes[1]]["file_pruned"] is False
    assert by_hash[hashes[2]]["file_pruned"] is False


async def test_apply_failure_rollback_leaves_db_and_disk_untouched(
    service: ManualIngestService, red_tsdb_conn, tmp_path: Path, monkeypatch,
):
    """A mid-transaction failure rolls back DELETE + INSERT (readings) +
    INSERT (manual_uploads). The previously-applied dataset survives, no
    new audit row is created, and no audit-row-referenced file is removed.
    """
    from dataclasses import replace

    from wp6_data.red.sijia.parser import parse as real_parse

    # Bedrock: one successful apply so there's prior state to "leave alone".
    good_payload = _tiny_sijia_xlsx(10.0)
    good_report = await service.validate(good_payload)
    good_apply = await service.apply(good_report.file_hash, filename="good.xlsx")
    good_path = tmp_path / "sijia" / f"{good_report.file_hash}.xlsx"
    assert good_path.exists()

    # Now arrange the next apply to fail at INSERT (readings) by giving one
    # Reading a NULL device_name — violates the TEXT NOT NULL constraint.
    def bad_parse(file_bytes):
        readings = list(real_parse(file_bytes))
        readings[-1] = replace(readings[-1], device_name=None)
        return readings

    # Inject the bad parser through the ManualSource descriptor — the only
    # per-source seam the shared engine resolves parse() from. (Retargeted
    # from monkeypatching the old red-only service module's `parse`.)
    monkeypatch.setattr(
        service, "_source", replace(service._source, parse=bad_parse),
    )

    bad_payload = _tiny_sijia_xlsx(99.0)
    bad_report = await service.validate(bad_payload)
    import psycopg.errors
    with pytest.raises(psycopg.errors.NotNullViolation):
        await service.apply(bad_report.file_hash, filename="bad.xlsx")

    # DB: the prior good_apply's rows must still be present (DELETE rolled back).
    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT COUNT(*) AS n FROM readings WHERE upload_id = %s",
            (good_apply.upload_id,),
        )
        assert (await cur.fetchone())["n"] == good_apply.row_count

        # No new audit row was committed by the failed apply.
        await cur.execute(
            "SELECT COUNT(*) AS n FROM manual_uploads WHERE source = 'sijia'",
        )
        assert (await cur.fetchone())["n"] == 1

    # Disk: the good apply's file (the only audit-row-referenced one) is intact.
    assert good_path.exists()


async def test_validate_returns_comparison_facts_against_existing_data(
    service: ManualIngestService,
):
    """validate() enriches the parser's ValidationReport with comparison facts:
    existing_row_count, existing_date_range, devices_removed, sensors_removed.
    """
    # Establish prior state: apply the full seed (2 devices, many sensors).
    seed_bytes = SEED_PATH.read_bytes()
    seed_report = await service.validate(seed_bytes)
    seed_result = await service.apply(seed_report.file_hash, filename="seed.xlsx")

    # New upload uses a different device (TestVariety, never in seed)
    # and only chlorophyll — so seed's devices and most sensors are "removed".
    tiny_bytes = _tiny_sijia_xlsx(10.0)
    report = await service.validate(tiny_bytes)

    assert report.existing_row_count == seed_result.row_count
    assert report.existing_date_range is not None
    # Seed has >= 2 devices, none of which are in the tiny payload.
    assert set(report.devices_removed) >= {
        "neurath-B-2034-strabelina", "neurath-B-2012-shivious",
    }
    # Tiny only carries `chlorophyll`; everything else seed had is "removed".
    assert "chlorophyll" not in report.sensors_removed
    assert len(report.sensors_removed) >= 1
