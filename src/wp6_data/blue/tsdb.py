"""TimescaleDB schema bootstrap for the blue twin.

Blue's `readings` has a different column shape than red's: a `project`
column (the automated yookr-vs-datalake view) plus a `source` column for
manual-ingest provenance (mirroring red's `source` — distinct concepts, not
a rename; see ``project_blue_project_vs_red_source`` memo) and a nullable
`upload_id` FK to `manual_uploads` for rows that came from a manual upload.

The cagg + `sync_metadata` + `daily_coverage` infrastructure is twin-agnostic
and lives in `wp6_data.db.schema`/`queries`; `ensure_schema_blue` delegates to
`ensure_aggregates(pool, project_column="project")` after creating blue's
readings hypertable.

Mirrors `wp6_data.red.tsdb`: each twin owns its own readings DDL +
`ensure_schema_*` symmetrically, so `db.schema` stays twin-agnostic.
"""

from __future__ import annotations

import structlog
from psycopg_pool import AsyncConnectionPool

from wp6_data.db.schema import MANUAL_UPLOADS_SQL, ensure_aggregates

logger = structlog.get_logger()

# Blue's readings hypertable. Red has its own DDL in `wp6_data.red.tsdb`.
_READINGS_BLUE_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    time        TIMESTAMPTZ      NOT NULL,
    device_name TEXT             NOT NULL,
    sensor_tag  TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    raw_value   TEXT,
    project     TEXT             NOT NULL DEFAULT 'unknown',
    source      TEXT             NOT NULL DEFAULT 'unknown',
    synced_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_readings_device_tag
    ON readings (device_name, sensor_tag, time DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup
    ON readings (device_name, sensor_tag, time);
"""

# Blue's readings gains the same nullable FK red's readings has, added
# idempotently. Adding a nullable column with no default is metadata-only on
# the hypertable; the FK targets the plain `manual_uploads` table, so it is
# valid on a hypertable (the referencing side may be a hypertable). IF NOT
# EXISTS makes the whole clause — column and its inline FK — idempotent.
_BLUE_UPLOAD_ID_SQL = """
ALTER TABLE readings
    ADD COLUMN IF NOT EXISTS upload_id BIGINT REFERENCES manual_uploads(id);
"""

# Blue's manual-ingest categorical, mirroring red's `source` column. Distinct
# from `project` (the automated yookr-vs-datalake view): automated rows keep
# the 'unknown' default; a manual upload sets it (e.g. 'insects'). Added
# idempotently for existing blue databases (metadata-only, like upload_id).
_BLUE_SOURCE_SQL = """
ALTER TABLE readings
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_readings_manual_source
    ON readings (source) WHERE source <> 'unknown';
"""


async def ensure_schema_blue(pool: AsyncConnectionPool) -> None:
    """Ensure blue's full TSDB schema (manual_uploads + readings + FK + cagg).

    Order matters: ``manual_uploads`` must exist before the ``upload_id`` FK
    is added to ``readings``. All idempotent — safe to run on every startup,
    including on a pre-existing blue database (the ALTER is a no-op once the
    column exists).
    """
    async with pool.connection() as conn:
        await conn.execute(MANUAL_UPLOADS_SQL)
        await conn.execute(_READINGS_BLUE_SQL)
        await conn.execute(_BLUE_UPLOAD_ID_SQL)
        await conn.execute(_BLUE_SOURCE_SQL)
        await conn.commit()
    await ensure_aggregates(pool, project_column="project")
    logger.info("blue_tsdb_schema_ensured")
