"""E2E: the red export job's TSDB leg writes one wide CSV per readings device.

The MySQL legs (sensor tables, wire heights) are covered by the job's own
shape; what needed a real database is the TSDB leg: that a LetsGrow row in
`readings` ends up in `letsgrow-climate-b4.csv` as a pivoted column, and that
the device lands in the export metadata the explorer's Exports tab reads.
"""

import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import RED_TSDB_DSN, remove_cagg_refresh_policy
from wp6_data.api.models import LetsGrowReading
from wp6_data.db.pool import close_pool, init_pool
from wp6_data.db.queries import upsert_readings
from wp6_data.red import export, letsgrow
from wp6_data.red.export import export_tsdb_device, get_tsdb_device_names
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.shared.blob import LocalBlobStore
from wp6_data.shared.export import METADATA_KEY, csv_key, get_export_metadata

pytestmark = pytest.mark.e2e

ROW_TEMP = LetsGrowReading.model_validate({
    "module_id": 39887,
    "module_name": "Climate B4",
    "col_id": 1467902,
    "description": "Temperature greenhouse - °C - 5 min",
    "timestamp": "2026-10-15T14:00:00",
    "value": 21.5,
})
ROW_VPD = LetsGrowReading.model_validate({
    "module_id": 39887,
    "module_name": "Climate B4",
    "col_id": 1467551,
    "description": "Greenhouse: VPD - kPa - 5 min",
    "timestamp": "2026-10-15T14:00:00",
    "value": 0.9,
})


async def _drop_red_schema(conn) -> None:
    """Same teardown as test_letsgrow_ingest: cagg before the hypertable."""
    await remove_cagg_refresh_policy(conn)
    async with conn.cursor() as cur:
        await cur.execute("DROP MATERIALIZED VIEW IF EXISTS sensors_daily_summary")
        await cur.execute("DROP TABLE IF EXISTS sync_metadata CASCADE")
        await cur.execute("DROP TABLE IF EXISTS sync_run_history CASCADE")
        await cur.execute("DROP TABLE IF EXISTS readings CASCADE")
        await cur.execute("DROP TABLE IF EXISTS manual_uploads CASCADE")
    await conn.commit()


@pytest.fixture()
async def red_pool(red_tsdb_conn, tmp_path):
    await _drop_red_schema(red_tsdb_conn)
    pool = AsyncConnectionPool(RED_TSDB_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    await ensure_schema_red(pool)
    # The export module reads the global pool; point it at the e2e database.
    await close_pool()
    await init_pool(RED_TSDB_DSN, min_size=1, max_size=2)
    yield pool, LocalBlobStore(tmp_path)
    await close_pool()
    await pool.close()
    await _drop_red_schema(red_tsdb_conn)


async def test_tsdb_device_is_exported_wide(red_pool):
    pool, store = red_pool
    async with pool.connection() as conn:
        await upsert_readings(
            conn,
            [letsgrow.to_params(ROW_TEMP), letsgrow.to_params(ROW_VPD)],
            source=letsgrow.SOURCE,
        )
        await conn.commit()

    assert await get_tsdb_device_names() == ["letsgrow-climate-b4"]

    key = await export_tsdb_device("letsgrow-climate-b4", store)
    assert key == csv_key("letsgrow-climate-b4")

    raw = await store.try_get(key)
    df = pd.read_csv(pd.io.common.BytesIO(raw))
    # One row per timestamp, one column per lg_* tag, sorted by tag.
    assert list(df.columns) == ["time", "lg_temp_greenhouse", "lg_vpd"]
    assert len(df) == 1
    assert df.loc[0, "lg_temp_greenhouse"] == 21.5
    assert df.loc[0, "lg_vpd"] == 0.9
    # 14:00 Amsterdam summer time -> 12:00 UTC.
    assert df.loc[0, "time"] == "2026-10-15 12:00:00+00:00"


async def test_tsdb_export_pivots_across_timestamps_and_pages(red_pool, monkeypatch):
    """The streaming pivot: multiple timestamps interleaved with tags come
    out as one wide row per timestamp, and a page boundary mid-device does
    not split or drop rows. 5-min steps from 2026-10-15 stay inside one
    DST season only for ~5 months; the spring-forward gap (2027-03-28)
    collapses 24 local stamps onto existing UTC rows by design (the dedup
    index), so the expected row count is the number of distinct UTC
    instants, computed here rather than hard-coded."""
    # Shrink the page so the test stays fast: what matters is crossing page
    # boundaries mid-device, not the absolute row count. At the production
    # page size this inserted 401k rows through the per-row upsert and alone
    # took ~90s -- two thirds of the whole e2e suite in CI.
    monkeypatch.setattr(export, "_TSDB_EXPORT_PAGE", 500)
    pool, store = red_pool
    n = 2 * export._TSDB_EXPORT_PAGE + 500  # crosses two page boundaries
    base = datetime(2026, 10, 15, 12, 0)  # naive local, Amsterdam CEST = UTC+2
    from zoneinfo import ZoneInfo
    ams = ZoneInfo("Europe/Amsterdam")
    expected_rows = len({
        (base + timedelta(minutes=5 * i)).replace(tzinfo=ams).astimezone(UTC)
        for i in range(n)
    })
    rows = []
    for i in range(n):
        ts = (base + timedelta(minutes=5 * i)).isoformat()
        for col_id, value in ((1467902, 20.0 + i / 1000), (1467551, 0.5 + i / 1000)):
            rows.append(letsgrow.to_params(LetsGrowReading.model_validate({
                "module_id": 39887,
                "module_name": "Climate B4",
                "col_id": col_id,
                "description": "x",
                "timestamp": ts,
                "value": value,
            })))
    async with pool.connection() as conn:
        for chunk_start in range(0, len(rows), 5000):
            await upsert_readings(
                conn, rows[chunk_start:chunk_start + 5000], source=letsgrow.SOURCE,
            )
        await conn.commit()

    key = await export_tsdb_device("letsgrow-climate-b4", store)
    raw = await store.try_get(key)
    parsed = list(csv.reader(io.StringIO(raw.decode())))
    assert parsed[0] == ["time", "lg_temp_greenhouse", "lg_vpd"]
    # Every distinct timestamp got exactly one row, in order, no gaps at
    # page edges.
    assert len(parsed) - 1 == expected_rows
    assert parsed[1][0].startswith("2026-10-15 10:00:00")  # 12:00 CEST -> 10:00 UTC
    assert float(parsed[1][1]) == 20.0
    # Rows are time-ordered.
    times = [row[0] for row in parsed[1:]]
    assert times == sorted(times)


async def test_tsdb_device_without_rows_exports_nothing(red_pool):
    pool, store = red_pool
    async with pool.connection() as conn:
        await upsert_readings(
            conn, [letsgrow.to_params(ROW_TEMP)], source=letsgrow.SOURCE
        )
        await conn.commit()

    assert await export_tsdb_device("letsgrow-water-b4", store) is None
    assert await store.try_get(csv_key("letsgrow-water-b4")) is None


async def test_export_metadata_lists_tsdb_devices_for_the_explorer(red_pool):
    """The Exports tab reads metadata.json; a TSDB device must appear in it."""
    pool, store = red_pool
    async with pool.connection() as conn:
        await upsert_readings(
            conn, [letsgrow.to_params(ROW_TEMP)], source=letsgrow.SOURCE
        )
        await conn.commit()

    key = await export_tsdb_device("letsgrow-climate-b4", store)
    assert key is not None
    exported_at = datetime.now(UTC).isoformat()
    await store.put(
        METADATA_KEY,
        json.dumps({
            "exported_at": exported_at,
            "devices": {"letsgrow-climate-b4": exported_at},
        }).encode(),
    )

    meta = await get_export_metadata(store)
    assert meta["devices"] == {"letsgrow-climate-b4": exported_at}


async def test_tsdb_export_reads_sijia_rows_too(red_pool):
    """Every readings device is exported, not just letsgrow's."""
    pool, store = red_pool
    sijia_row = {
        "device_name": "neurath-B-2034-strabelina",
        "sensor_tag": "chlorophyll",
        "value": "12.3",
        "datetime_measure": "2026-10-15T12:00:00+00:00",
    }
    async with pool.connection() as conn:
        await upsert_readings(conn, [sijia_row], source="sijia")
        await conn.commit()

    assert "neurath-B-2034-strabelina" in await get_tsdb_device_names()
    key = await export_tsdb_device("neurath-B-2034-strabelina", store)
    raw = await store.try_get(key)
    df = pd.read_csv(pd.io.common.BytesIO(raw))
    assert list(df.columns) == ["time", "chlorophyll"]
    assert df.loc[0, "chlorophyll"] == 12.3
