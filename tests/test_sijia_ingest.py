"""Tests for the Sijia CLI ingest pipeline.

Mostly unit-mocked at the AsyncConnectionPool boundary. One e2e smoke test
against the real wp6_red TSDB lives in tests/e2e/test_sijia_ingest.py.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wp6_data.red.sijia.ingest import IngestResult, ingest_sijia_file, main
from wp6_data.red.sijia.parser import SijiaParseError

SEED_PATH = Path(__file__).parent / "fixtures" / "sijia_seed.xlsx"


def _make_pool(*, returning_upload_id: int = 42):
    """Build a mock AsyncConnectionPool whose connection() yields a conn that:

    - returns the given upload_id when INSERT INTO manual_uploads ... RETURNING id is called
    - accepts an executemany() for the readings batch
    - records commit/rollback calls so tests can assert them
    """
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value={"id": returning_upload_id})

    cursor_ctx = AsyncMock()
    cursor_ctx.__aenter__ = AsyncMock(return_value=cursor)
    cursor_ctx.__aexit__ = AsyncMock(return_value=False)

    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=cursor_ctx)

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn_ctx)
    return pool, conn, cursor


@pytest.mark.asyncio()
async def test_ingest_seed_file_returns_result_with_upload_id_and_row_count():
    pool, _conn, _cursor = _make_pool(returning_upload_id=42)

    result = await ingest_sijia_file(pool, SEED_PATH)

    assert isinstance(result, IngestResult)
    assert result.upload_id == 42
    assert result.row_count > 0


@pytest.mark.asyncio()
async def test_db_failure_during_insert_does_not_commit():
    """If the bulk insert raises, the transaction must NOT be committed."""
    pool, conn, cursor = _make_pool(returning_upload_id=11)
    cursor.executemany.side_effect = RuntimeError("boom — simulated DB error")

    with pytest.raises(RuntimeError, match="boom"):
        await ingest_sijia_file(pool, SEED_PATH)

    conn.commit.assert_not_awaited()


def test_main_invokes_ingest_with_path_from_argv():
    """`wp6-red-ingest-sijia <path>` must dispatch to ingest_sijia_file with that path."""
    captured: dict = {}

    async def fake_ingest(pool, path):
        captured["pool"] = pool
        captured["path"] = path
        return IngestResult(upload_id=1, row_count=1)

    with (
        patch("sys.argv", ["wp6-red-ingest-sijia", "/tmp/foo.xlsx"]),
        patch("wp6_data.red.sijia.ingest.ingest_sijia_file", side_effect=fake_ingest),
        patch("wp6_data.red.sijia.ingest.AsyncConnectionPool") as MockPool,
    ):
        pool_instance = AsyncMock()
        MockPool.return_value = pool_instance
        main()

    assert captured["path"] == Path("/tmp/foo.xlsx")
    pool_instance.open.assert_awaited()
    pool_instance.close.assert_awaited()


@pytest.mark.asyncio()
async def test_parser_failure_propagates_and_does_not_touch_the_db(tmp_path):
    """A structurally bad file must raise SijiaParseError without opening a DB transaction."""
    bad_xlsx = tmp_path / "bad.xlsx"
    # Write a minimal xlsx with the wrong sheet name so validate() raises.
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "WrongSheet"
    wb.save(bad_xlsx)

    pool, _conn, cursor = _make_pool()

    with pytest.raises(SijiaParseError):
        await ingest_sijia_file(pool, bad_xlsx)

    # No DB connection should have been opened, so no execute / commit calls.
    pool.connection.assert_not_called()
    cursor.execute.assert_not_awaited()


@pytest.mark.asyncio()
async def test_ingest_deletes_existing_sijia_rows_before_inserting():
    """Re-running the ingest must purge prior source='sijia' rows in the same transaction."""
    pool, _conn, cursor = _make_pool(returning_upload_id=7)

    await ingest_sijia_file(pool, SEED_PATH)

    # Find the DELETE call and assert it targets source='sijia' AND happens before the audit row.
    executes = [c.args[0] for c in cursor.execute.await_args_list]
    delete_idx = next(
        (i for i, sql in enumerate(executes) if "DELETE FROM readings" in sql),
        None,
    )
    insert_audit_idx = next(
        (i for i, sql in enumerate(executes) if "INSERT INTO manual_uploads" in sql),
        None,
    )
    assert delete_idx is not None, f"no DELETE issued; saw: {executes!r}"
    assert insert_audit_idx is not None
    assert delete_idx < insert_audit_idx, (
        "DELETE must precede the audit INSERT so the new audit row is the only "
        "one referenced by readings"
    )
    delete_sql = executes[delete_idx]
    assert "source" in delete_sql.lower()


@pytest.mark.asyncio()
async def test_ingest_bulk_inserts_readings_with_upload_id_and_source():
    """Every parsed Reading is bulk-inserted, tagged with the new upload_id and source='sijia'."""
    pool, _conn, cursor = _make_pool(returning_upload_id=99)

    result = await ingest_sijia_file(pool, SEED_PATH)

    assert cursor.executemany.await_count == 1
    sql, params = cursor.executemany.await_args.args
    assert "INSERT INTO readings" in sql
    assert len(params) == result.row_count
    # Every row carries the upload_id from the audit insert and source='sijia'
    assert all(p["upload_id"] == 99 for p in params)
    assert all(p["source"] == "sijia" for p in params)
