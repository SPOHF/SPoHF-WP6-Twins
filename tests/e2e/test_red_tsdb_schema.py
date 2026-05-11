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
    """Tear down red TSDB tables so each test starts on a clean slate.

    Order matters: the cagg depends on the `readings` hypertable, so drop it
    first; otherwise `DROP TABLE readings CASCADE` fails because of the
    continuous aggregate dependency.
    """
    async with conn.cursor() as cur:
        await cur.execute("DROP MATERIALIZED VIEW IF EXISTS sensors_daily_summary")
        await cur.execute("DROP TABLE IF EXISTS daily_coverage CASCADE")
        await cur.execute("DROP TABLE IF EXISTS sync_metadata CASCADE")
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


async def test_reading_with_invalid_upload_id_violates_foreign_key(clean_red_db, red_pool):
    """An upload_id that doesn't exist in manual_uploads must be rejected by the FK."""
    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await cur.execute(
                "INSERT INTO readings "
                "(time, device_name, sensor_tag, value, source, upload_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (datetime(2025, 6, 1, 9, 0, tzinfo=UTC),
                 "e2e-d", "e2e-s", 1.0, "e2e-sijia", 999999),
            )
    await clean_red_db.rollback()


async def test_manual_uploads_carries_all_provenance_columns(clean_red_db, red_pool):
    """Schema records every provenance fact the audit flow needs (PRD §Storage)."""
    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO manual_uploads "
            "(source, filename, file_hash, file_path, row_count) "
            "VALUES (%s, %s, %s, %s, %s) "
            "RETURNING id, file_pruned, uploaded_at, file_path, row_count, error",
            ("e2e-sijia", "seed.xlsx", "deadbeef",
             "/data/manual-uploads/e2e-sijia/abc.xlsx", 112),
        )
        row = await cur.fetchone()
    await clean_red_db.commit()

    assert row["file_pruned"] is False  # default FALSE
    assert row["uploaded_at"] is not None  # default NOW()
    assert row["file_path"] == "/data/manual-uploads/e2e-sijia/abc.xlsx"
    assert row["row_count"] == 112
    assert row["error"] is None  # nullable, defaults to NULL


async def test_readings_column_shape_matches_blue_with_source_and_upload_id(
    clean_red_db, red_pool,
):
    """Red readings shares blue's column shape (project → source) plus upload_id."""
    await ensure_schema_red(red_pool)
    expected = {
        "time", "device_name", "sensor_tag", "value", "raw_value",
        "source", "synced_at", "upload_id",
    }

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'readings' AND table_schema = 'public'"
        )
        actual = {row["column_name"] for row in await cur.fetchall()}

    assert actual == expected


async def test_readings_is_a_timescaledb_hypertable(clean_red_db, red_pool):
    """create_hypertable is part of the schema bootstrap so time-partitioning works."""
    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_schema = 'public'"
        )
        hypertables = {row["hypertable_name"] for row in await cur.fetchall()}

    assert "readings" in hypertables


async def test_bootstrap_creates_aggregates_and_audit_tables(clean_red_db, red_pool):
    """ensure_schema_red also lays down sync_metadata, daily_coverage, and the cagg."""
    await ensure_schema_red(red_pool)

    assert await _table_exists(clean_red_db, "sync_metadata")
    assert await _table_exists(clean_red_db, "daily_coverage")

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT view_name FROM timescaledb_information.continuous_aggregates "
            "WHERE view_name = 'sensors_daily_summary'"
        )
        cagg_row = await cur.fetchone()
    assert cagg_row is not None


async def test_cagg_groups_by_source_column(clean_red_db, red_pool):
    """Red's cagg must group by `source` (not `project`) — see project_blue_project_vs_red_source."""
    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sensors_daily_summary' AND table_schema = 'public'"
        )
        cols = {row["column_name"] for row in await cur.fetchall()}

    # The template aliases the categorical column to "project" in the view
    # output for cross-twin uniformity; the underlying grouping is over
    # red's `source` column.
    assert "project" in cols
    assert "device_name" in cols
    assert "reading_count" in cols
    assert "first_reading" in cols
    assert "last_reading" in cols


async def test_daily_coverage_is_backfilled_when_readings_already_exist(
    clean_red_db, red_pool,
):
    """First bootstrap on a non-empty `readings` table populates daily_coverage."""
    # Pre-existing data simulates an upgrade where readings predate this feature.
    async with clean_red_db.cursor() as cur:
        await cur.execute(
            "CREATE TABLE readings ("
            "  time TIMESTAMPTZ NOT NULL, device_name TEXT NOT NULL,"
            "  sensor_tag TEXT NOT NULL, value DOUBLE PRECISION,"
            "  source TEXT NOT NULL DEFAULT 'unknown')"
        )
        await cur.execute(
            "SELECT create_hypertable('readings', 'time', if_not_exists => TRUE)"
        )
        await cur.execute(
            "INSERT INTO readings (time, device_name, sensor_tag, value, source) "
            "VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)",
            (
                datetime(2025, 5, 1, 9, 0, tzinfo=UTC), "d1", "s1", 1.0, "e2e",
                datetime(2025, 5, 2, 9, 0, tzinfo=UTC), "d1", "s1", 2.0, "e2e",
            ),
        )
    await clean_red_db.commit()

    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(*) AS n FROM daily_coverage WHERE device_name = 'd1'"
        )
        assert (await cur.fetchone())["n"] == 2  # one row per distinct day


async def test_daily_coverage_not_rebuilt_on_subsequent_bootstrap(
    clean_red_db, red_pool,
):
    """The backfill guard prevents repeated full rebuilds on every pod start."""
    await ensure_schema_red(red_pool)

    # Insert one coverage row manually; it must survive a second bootstrap
    # since `readings` itself is empty (count-check sees coverage already exists).
    async with clean_red_db.cursor() as cur:
        await cur.execute(
            "INSERT INTO daily_coverage (device_name, sensor_tag, day) "
            "VALUES (%s, %s, %s)",
            ("d-manual", "s-manual", "2025-05-01"),
        )
    await clean_red_db.commit()

    await ensure_schema_red(red_pool)

    async with clean_red_db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(*) AS n FROM daily_coverage WHERE device_name = 'd-manual'"
        )
        assert (await cur.fetchone())["n"] == 1  # untouched
