"""E2E tests for the twin-agnostic UploadStorage helper.

Covers issue 008: write/read of upload bytes onto a PVC-style mount, plus
the 2-file-per-source prune policy that keeps disk usage bounded while
preserving manual_uploads audit rows indefinitely.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.shared.blob import LocalBlobStore
from wp6_data.shared.upload_storage import UploadStorage

pytestmark = pytest.mark.e2e

E2E_SOURCE = "e2e-storage"


async def _purge(conn) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM readings WHERE source = %s", (E2E_SOURCE,),
        )
        await cur.execute(
            "DELETE FROM manual_uploads WHERE source = %s", (E2E_SOURCE,),
        )
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


async def test_write_persists_under_the_source_prefix_and_returns_hash(
    red_pool, tmp_path: Path,
):
    store = LocalBlobStore(tmp_path)
    storage = UploadStorage(store=store, pool=red_pool)
    file_bytes = b"hello, sijia"

    key, file_hash = await storage.write(E2E_SOURCE, file_bytes)

    import hashlib
    assert file_hash == hashlib.sha256(file_bytes).hexdigest()

    # Content-addressed, under the per-source prefix.
    assert key == f"{E2E_SOURCE}/{file_hash}.xlsx"
    assert await store.get(key) == file_bytes


async def test_read_round_trips_written_bytes(red_pool, tmp_path: Path):
    storage = UploadStorage(store=LocalBlobStore(tmp_path), pool=red_pool)
    file_bytes = b"chlorophyll,42.7\nflavonoids,13.1\n"
    key, _hash = await storage.write(E2E_SOURCE, file_bytes)

    assert await storage.read(key) == file_bytes


async def _seed_three_uploads(
    storage: UploadStorage, conn,
) -> list[tuple[str, str]]:
    """Write 3 distinct objects for E2E_SOURCE and 3 audit rows with controlled
    uploaded_at, ordered oldest → newest. Returns [(key, file_hash), ...] in
    that same order, so callers can assert "the first one" is the oldest.
    """
    from datetime import UTC, datetime

    timestamps = [
        datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
        datetime(2025, 2, 1, 9, 0, tzinfo=UTC),
        datetime(2025, 3, 1, 9, 0, tzinfo=UTC),
    ]
    files: list[tuple[str, str]] = []
    for i, ts in enumerate(timestamps):
        key, file_hash = await storage.write(E2E_SOURCE, f"file-{i}-bytes".encode())
        files.append((key, file_hash))
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO manual_uploads "
                "(source, filename, file_hash, file_path, uploaded_at, row_count) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (E2E_SOURCE, f"file-{i}.xlsx", file_hash, key, ts, 0),
            )
        await conn.commit()
    return files


async def test_prune_removes_objects_older_than_latest_two_per_source(
    red_pool, red_tsdb_conn, tmp_path: Path,
):
    store = LocalBlobStore(tmp_path)
    storage = UploadStorage(store=store, pool=red_pool)
    files = await _seed_three_uploads(storage, red_tsdb_conn)
    oldest, middle, newest = files

    await storage.prune(E2E_SOURCE)

    assert not await store.exists(oldest[0]), "oldest object should be removed"
    assert await store.exists(middle[0]), "middle (2nd-newest) must survive"
    assert await store.exists(newest[0]), "newest must survive"


async def test_prune_marks_older_audit_rows_pruned_and_keeps_them_in_db(
    red_pool, red_tsdb_conn, tmp_path: Path,
):
    storage = UploadStorage(store=LocalBlobStore(tmp_path), pool=red_pool)
    files = await _seed_three_uploads(storage, red_tsdb_conn)

    await storage.prune(E2E_SOURCE)

    async with red_tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT file_hash, file_path, file_pruned "
            "FROM manual_uploads WHERE source = %s "
            "ORDER BY uploaded_at",
            (E2E_SOURCE,),
        )
        rows = await cur.fetchall()

    # All 3 audit rows preserved — prune NEVER deletes provenance.
    assert len(rows) == 3
    oldest_row, middle_row, newest_row = rows

    # Oldest row: marked pruned, file_path nulled out.
    assert oldest_row["file_hash"] == files[0][1]
    assert oldest_row["file_path"] is None
    assert oldest_row["file_pruned"] is True

    # Latest two rows: untouched.
    assert middle_row["file_path"] == str(files[1][0])
    assert middle_row["file_pruned"] is False
    assert newest_row["file_path"] == str(files[2][0])
    assert newest_row["file_pruned"] is False
