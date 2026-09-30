"""Manual uploads round-trip through a real S3, including the legacy-path shim.

Phase 3 of issue 061, and the one genuinely irreplaceable dataset of the three:
exports regenerate nightly and models refit, but these are source files that
exist nowhere else. The `manual_uploads` audit table is the system of record and
points at them by key.

`stored_key` itself is pure and tested in tests/test_upload_storage_keys.py;
what is checked here is that prune actually deletes the right object when the
audit row records a legacy absolute path — the silent leak the shim prevents.
"""

import hashlib

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.shared.blob import PrefixedBlobStore
from wp6_data.shared.upload_storage import UploadStorage

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

SOURCE = "e2e-uploads"


async def _purge(conn) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM manual_uploads WHERE source LIKE %s", ("e2e-%",))
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


@pytest.fixture
def uploads(s3_store):
    return PrefixedBlobStore(s3_store, "red/manual-uploads")


@pytest.fixture
def storage(uploads, red_pool):
    return UploadStorage(store=uploads, pool=red_pool)


async def test_write_is_content_addressed_under_the_source_prefix(storage, uploads):
    file_bytes = b"chlorophyll,42.7\n"

    key, file_hash = await storage.write(SOURCE, file_bytes)

    assert file_hash == hashlib.sha256(file_bytes).hexdigest()
    assert key == f"{SOURCE}/{file_hash}.xlsx"
    assert await uploads.get(key) == file_bytes


async def test_writing_the_same_bytes_twice_is_idempotent(storage, uploads):
    """Content addressing: the hash is the validation_id the upload flow uses,
    so a re-upload of identical bytes must land in the same place."""
    first, hash_a = await storage.write(SOURCE, b"same bytes")
    second, hash_b = await storage.write(SOURCE, b"same bytes")

    assert first == second
    assert hash_a == hash_b
    assert await uploads.list(f"{SOURCE}/") == [first]


async def test_suffix_follows_the_source_descriptor(storage):
    """Blue's sources are CSV, red's are xlsx — the key must say which."""
    key, _ = await storage.write(SOURCE, b"a,b\n1,2\n", suffix=".csv")

    assert key.endswith(".csv")


async def test_read_round_trips(storage):
    key, _ = await storage.write(SOURCE, b"flavonoids,13.1\n")

    assert await storage.read(key) == b"flavonoids,13.1\n"


async def test_sources_do_not_collide(storage, uploads):
    """Same bytes, two sources: one object each, under its own prefix."""
    other = "e2e-insects"
    a, _ = await storage.write(SOURCE, b"identical")
    b, _ = await storage.write(other, b"identical")

    assert a != b
    assert await uploads.list(f"{SOURCE}/") == [a]
    assert await uploads.list(f"{other}/") == [b]


async def test_prune_deletes_an_object_recorded_by_a_legacy_absolute_path(
    storage, uploads, red_pool, red_tsdb_conn,
):
    """The regression the shim exists for.

    Three uploads, all recorded the old way — absolute paths. Prune must still
    find and delete the oldest object rather than silently leaving it behind.
    """
    from datetime import UTC, datetime

    keys = []
    for i, ts in enumerate([
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        datetime(2025, 3, 1, tzinfo=UTC),
    ]):
        key, file_hash = await storage.write(SOURCE, f"legacy-{i}".encode())
        keys.append(key)
        async with red_tsdb_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO manual_uploads "
                "(source, filename, file_hash, file_path, uploaded_at, row_count) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                # Recorded the pre-migration way.
                (SOURCE, f"f{i}.xlsx", file_hash, f"/data/manual-uploads/{key}", ts, 0),
            )
        await red_tsdb_conn.commit()

    removed = await storage.prune(SOURCE)

    assert removed == [keys[0]], "prune should report the normalised key"
    assert not await uploads.exists(keys[0]), "oldest object must actually be gone"
    assert await uploads.exists(keys[1])
    assert await uploads.exists(keys[2])


async def test_prune_spares_an_object_a_retained_row_still_points_at(
    storage, uploads, red_pool, red_tsdb_conn,
):
    """The data-loss bug this exists to prevent.

    Uploads are content-addressed, so re-uploading identical bytes produces a
    second audit row naming the SAME object. `long_data` does this every year —
    the same workbook is re-issued — and blue lost both its live uploads when
    prune deleted the older row's file, which was the newer row's file too.

    Three rows, two of them the same bytes: the newest (id 3) and the oldest
    (id 1) share a key. Pruning row 1 must mark it pruned but leave the object,
    because row 3 is retained and still needs it.
    """
    from datetime import UTC, datetime

    shared_key, shared_hash = await storage.write(SOURCE, b"re-issued workbook")
    other_key, other_hash = await storage.write(SOURCE, b"a different upload")

    rows = [
        # oldest: same bytes as the newest -> same key
        (datetime(2025, 1, 1, tzinfo=UTC), shared_hash, shared_key),
        (datetime(2025, 2, 1, tzinfo=UTC), other_hash, other_key),
        # newest: the re-upload
        (datetime(2025, 3, 1, tzinfo=UTC), shared_hash, shared_key),
    ]
    for ts, fhash, key in rows:
        async with red_tsdb_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO manual_uploads "
                "(source, filename, file_hash, file_path, uploaded_at, row_count) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (SOURCE, "Long_Data 2024.xlsx", fhash, key, ts, 0),
            )
        await red_tsdb_conn.commit()

    removed = await storage.prune(SOURCE)

    assert removed == [], "the only prunable row shares its object with a kept row"
    assert await uploads.exists(shared_key), "object a retained row needs must survive"
    assert await uploads.exists(other_key)

    # The row is still marked pruned — it is no longer one of the latest two.
    async with red_tsdb_conn.cursor() as cur:
        await cur.execute(
            "SELECT file_pruned FROM manual_uploads WHERE source = %s "
            "ORDER BY uploaded_at",
            (SOURCE,),
        )
        assert [r[0] for r in await cur.fetchall()] == [True, False, False]


async def test_prune_still_deletes_an_object_nothing_retains(
    storage, uploads, red_pool, red_tsdb_conn,
):
    """The sparing rule must not turn prune into a no-op."""
    from datetime import UTC, datetime

    keys = []
    for i, ts in enumerate([
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        datetime(2025, 3, 1, tzinfo=UTC),
    ]):
        key, fhash = await storage.write(SOURCE, f"distinct-{i}".encode())
        keys.append(key)
        async with red_tsdb_conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO manual_uploads "
                "(source, filename, file_hash, file_path, uploaded_at, row_count) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (SOURCE, f"f{i}.xlsx", fhash, key, ts, 0),
            )
        await red_tsdb_conn.commit()

    assert await storage.prune(SOURCE) == [keys[0]]
    assert not await uploads.exists(keys[0])
    assert await uploads.exists(keys[1])
    assert await uploads.exists(keys[2])
