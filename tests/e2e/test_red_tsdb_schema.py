"""E2E: Bootstrap of the red TimescaleDB schema (readings + manual_uploads)."""

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN
from wp6_data.red.tsdb import ensure_schema_red

pytestmark = pytest.mark.e2e


async def _drop_red_schema(conn) -> None:
    """Tear down red TSDB tables so each test starts on a clean slate."""
    async with conn.cursor() as cur:
        await cur.execute("DROP TABLE IF EXISTS readings CASCADE")
        await cur.execute("DROP TABLE IF EXISTS manual_uploads CASCADE")
    await conn.commit()


@pytest.fixture()
async def clean_red_db(red_tsdb_conn):
    await _drop_red_schema(red_tsdb_conn)
    yield red_tsdb_conn
    await _drop_red_schema(red_tsdb_conn)


@pytest.fixture()
async def red_pool():
    pool = AsyncConnectionPool(RED_TSDB_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    yield pool
    await pool.close()


async def _table_exists(conn, name: str) -> bool:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (name,),
        )
        return (await cur.fetchone()) is not None


async def test_bootstrap_creates_readings_and_manual_uploads(clean_red_db, red_pool):
    await ensure_schema_red(red_pool)

    assert await _table_exists(clean_red_db, "readings")
    assert await _table_exists(clean_red_db, "manual_uploads")


async def test_bootstrap_is_idempotent(clean_red_db, red_pool):
    await ensure_schema_red(red_pool)
    await ensure_schema_red(red_pool)  # second run must not raise

    assert await _table_exists(clean_red_db, "readings")
    assert await _table_exists(clean_red_db, "manual_uploads")


async def test_reading_with_valid_upload_id_roundtrips(clean_red_db, red_pool):
    """Insert a manual_uploads row, then a reading that references it, then read it back."""
    await ensure_schema_red(red_pool)

    measured_at = datetime(2025, 6, 1, 9, 0, tzinfo=UTC)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO manual_uploads "
            "(source, filename, file_hash, file_path, row_count) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            ("e2e-sijia", "neurath-2025.xlsx", "deadbeef", "/data/manual-uploads/x.xlsx", 1),
        )
        upload_id = (await cur.fetchone())["id"]

        await cur.execute(
            "INSERT INTO readings "
            "(time, device_name, sensor_tag, value, source, upload_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (measured_at, "e2e-neurath-B-2034-strabelina", "chlorophyll",
             12.4, "e2e-sijia", upload_id),
        )
    await clean_red_db.commit()

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT r.device_name, r.sensor_tag, r.value, r.source, "
            "       r.upload_id, u.file_pruned "
            "FROM readings r JOIN manual_uploads u ON r.upload_id = u.id "
            "WHERE r.source = %s",
            ("e2e-sijia",),
        )
        row = await cur.fetchone()

    assert row["device_name"] == "e2e-neurath-B-2034-strabelina"
    assert row["sensor_tag"] == "chlorophyll"
    assert row["value"] == 12.4
    assert row["source"] == "e2e-sijia"
    assert row["upload_id"] == upload_id
    assert row["file_pruned"] is False  # default value


async def test_duplicate_source_device_sensor_time_is_rejected(clean_red_db, red_pool):
    """The widened unique index forbids two rows with the same (source, device, sensor, time)."""
    await ensure_schema_red(red_pool)
    measured_at = datetime(2025, 6, 1, 9, 0, tzinfo=UTC)

    async with clean_red_db.cursor() as cur:
        await cur.execute(
            "INSERT INTO readings "
            "(time, device_name, sensor_tag, value, source) "
            "VALUES (%s, %s, %s, %s, %s)",
            (measured_at, "e2e-neurath-B-2034-strabelina", "chlorophyll", 12.4, "e2e-sijia"),
        )
    await clean_red_db.commit()

    with pytest.raises(psycopg.errors.UniqueViolation):
        async with clean_red_db.cursor() as cur:
            await cur.execute(
                "INSERT INTO readings "
                "(time, device_name, sensor_tag, value, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (measured_at, "e2e-neurath-B-2034-strabelina", "chlorophyll", 99.9, "e2e-sijia"),
            )
    await clean_red_db.rollback()


async def test_reading_with_null_upload_id_is_accepted(clean_red_db, red_pool):
    """Future automated-sync path: rows with upload_id NULL must be valid."""
    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO readings "
            "(time, device_name, sensor_tag, value, source, upload_id) "
            "VALUES (%s, %s, %s, %s, %s, NULL)",
            (datetime(2025, 6, 1, 9, 0, tzinfo=UTC),
             "e2e-letsgrow-1", "par", 800.0, "e2e-letsgrow"),
        )
        await cur.execute(
            "SELECT upload_id FROM readings WHERE source = %s",
            ("e2e-letsgrow",),
        )
        row = await cur.fetchone()
    await clean_red_db.commit()

    assert row["upload_id"] is None


async def test_same_device_sensor_time_can_coexist_across_sources(clean_red_db, red_pool):
    """Widening the unique index to include `source` is the whole point — verify it pays off."""
    await ensure_schema_red(red_pool)
    measured_at = datetime(2025, 6, 1, 9, 0, tzinfo=UTC)

    async with clean_red_db.cursor() as cur:
        await cur.execute(
            "INSERT INTO readings (time, device_name, sensor_tag, value, source) "
            "VALUES (%s, %s, %s, %s, %s)",
            (measured_at, "e2e-shared-device", "par", 700.0, "e2e-letsgrow"),
        )
        await cur.execute(
            "INSERT INTO readings (time, device_name, sensor_tag, value, source) "
            "VALUES (%s, %s, %s, %s, %s)",
            (measured_at, "e2e-shared-device", "par", 800.0, "e2e-sijia"),
        )
    await clean_red_db.commit()

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(*) AS n FROM readings WHERE device_name = %s",
            ("e2e-shared-device",),
        )
        assert (await cur.fetchone())["n"] == 2
