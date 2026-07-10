"""TimescaleDB schema bootstrap for the blue twin.

Blue's `readings` carries a `source` column for provenance (manual-ingest slug,
or 'unknown' for automated datalake rows) and a nullable `upload_id` FK to
`manual_uploads`. This matches red's single-categorical model: the `project`
column that once distinguished the yookr-direct and spohf-datalake pipelines
was dropped once the datalake became the only automated source.

The cagg + `sync_metadata` + `daily_coverage` infrastructure is twin-agnostic
and lives in `wp6_data.db.schema`/`queries`; `ensure_schema_blue` delegates to
`ensure_aggregates(pool, project_column="source")` after creating blue's
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
    source      TEXT             NOT NULL DEFAULT 'unknown',
    synced_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_readings_device_tag
    ON readings (device_name, sensor_tag, time DESC);

-- One automated source, so (device, sensor, time) identifies a reading. Manual
-- rows live on their own synthetic devices and cannot collide with it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_dedup_v3
    ON readings (device_name, sensor_tag, time);
"""

# Drop the superseded dedup indexes. Idempotent, and a no-op on a fresh DB.
# Ordered after the table DDL so the replacement index exists first.
_BLUE_DEDUP_MIGRATION_SQL = """
DROP INDEX IF EXISTS idx_readings_dedup;
DROP INDEX IF EXISTS idx_readings_dedup_v2;
"""

# `project` is dropped by scripts/migrate_blue_drop_project.sql, not here: the
# purge + cagg rebuild it requires are far too heavy for a startup path, and a
# half-applied schema is worse than a refusal to boot.
_PROJECT_COLUMN_EXISTS_SQL = """
SELECT 1 FROM information_schema.columns
WHERE table_name = 'readings' AND column_name = 'project'
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


class UnmigratedSchemaError(RuntimeError):
    """Raised when `readings.project` still exists — refuse to boot."""


async def ensure_schema_blue(pool: AsyncConnectionPool) -> None:
    """Ensure blue's full TSDB schema (manual_uploads + readings + FK + cagg).

    Order matters: ``manual_uploads`` must exist before the ``upload_id`` FK
    is added to ``readings``. All idempotent — safe to run on every startup,
    including on a pre-existing blue database (the ALTER is a no-op once the
    column exists).

    Refuses to run against a database that still has ``readings.project``. This
    code reads and upserts without it; proceeding would silently write to the
    wrong dedup key and, worse, the 3-column unique index below cannot even be
    built while both projects' rows coexist.
    """
    async with pool.connection() as conn:
        cur = await conn.execute(_PROJECT_COLUMN_EXISTS_SQL)
        if await cur.fetchone():
            raise UnmigratedSchemaError(
                "readings.project still exists — run "
                "scripts/migrate_blue_drop_project.sql before deploying this version "
                "(see docs/blue/yookr-direct-retirement.md)."
            )

        await conn.execute(MANUAL_UPLOADS_SQL)
        await conn.execute(_READINGS_BLUE_SQL)
        await conn.execute(_BLUE_UPLOAD_ID_SQL)
        await conn.execute(_BLUE_SOURCE_SQL)
        await conn.execute(_BLUE_DEDUP_MIGRATION_SQL)
        await conn.commit()
    await ensure_aggregates(pool, project_column="source")
    logger.info("blue_tsdb_schema_ensured")
