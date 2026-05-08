"""Tests for the Sijia CLI ingest command.

The CLI is now a thin wrapper around ManualIngestService — the bulk of the
behaviour (DELETE+INSERT atomicity, bulk-insert shape, rollback) is covered
by the service's e2e tests in ``tests/e2e/test_manual_ingest_service.py``.
What remains here are the CLI-specific contracts:

  - argv → path → service.validate+apply dispatch
  - parser-failure fast-fail: a structurally-bad file must raise without
    opening a DB connection.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wp6_data.red.sijia.ingest import ingest_sijia_file, main
from wp6_data.red.sijia.parser import SijiaParseError
from wp6_data.red.sijia.service import ApplyResult, ManualIngestService
from wp6_data.shared.upload_storage import UploadStorage


def _mock_pool():
    pool = MagicMock()
    pool.connection = MagicMock()
    return pool


def test_main_invokes_ingest_with_path_from_argv():
    """`wp6-red-ingest-sijia <path>` must dispatch to ingest_sijia_file with that path."""
    captured: dict = {}

    async def fake_ingest(service, path):
        captured["service"] = service
        captured["path"] = path
        return ApplyResult(upload_id=1, row_count=1)

    with (
        patch("sys.argv", ["wp6-red-ingest-sijia", "/tmp/foo.xlsx"]),
        patch("wp6_data.red.sijia.ingest.ingest_sijia_file", side_effect=fake_ingest),
        patch("wp6_data.red.sijia.ingest.AsyncConnectionPool") as MockPool,
    ):
        pool_instance = AsyncMock()
        MockPool.return_value = pool_instance
        main()

    assert captured["path"] == Path("/tmp/foo.xlsx")
    assert isinstance(captured["service"], ManualIngestService)
    pool_instance.open.assert_awaited()
    pool_instance.close.assert_awaited()


@pytest.mark.asyncio()
async def test_parser_failure_propagates_and_does_not_touch_the_db(tmp_path):
    """A structurally-bad file raises SijiaParseError without opening a DB connection.

    storage.write() is filesystem-only (no DB), so persisting the file as
    PRD §Upload flow specifies (line 285) is fine even on a bad file —
    what must not happen is any DB conversation.
    """
    bad_xlsx = tmp_path / "bad.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "WrongSheet"
    wb.save(bad_xlsx)

    pool = _mock_pool()
    storage = UploadStorage(base_dir=tmp_path, pool=pool)
    service = ManualIngestService(pool=pool, storage=storage)

    with pytest.raises(SijiaParseError):
        await ingest_sijia_file(service, bad_xlsx)

    pool.connection.assert_not_called()
