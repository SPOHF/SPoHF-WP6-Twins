"""E2E: blue's schema bootstrap indexes the manual rows of `readings`.

The home page asks for the latest manual reading per sensor on every load, and
blue's `readings` holds the whole datalake history, so an unindexed
`upload_id IS NOT NULL` filter scans every chunk to find a handful of rows.
"""

import pytest
from psycopg.rows import dict_row

from wp6_data.db.schema import MANUAL_READINGS_INDEX

pytestmark = pytest.mark.e2e


async def test_bootstrap_indexes_manual_readings(tsdb_conn):
    # The session fixture `_bootstrap_blue_schema` has already run ensure_schema_blue.
    async with tsdb_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'readings' AND indexname = %s",
            (MANUAL_READINGS_INDEX,),
        )
        row = await cur.fetchone()
    assert row is not None
    assert "upload_id IS NOT NULL" in row["indexdef"]
