"""E2E smoke test for the blue ``long_data`` ingest against a real TSDB.

Exercises the full path the CLI delegates into (decoder → upload storage →
transactional apply) using the **real** yearly Excel files. Those files are
gitignored, so the test skips when they are absent (it is a local smoke test).

Asserts the two behaviours unique to this source: per-year scoped replace
(ADR 0002) preserves other years, and sample multiplicity (ADR 0001) stores one
row per sample rather than a mean.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from tests.e2e.conftest import TSDB_DSN
from wp6_data.blue.long_data import LONG_DATA, SOURCE, parse
from wp6_data.shared.manual_ingest import ManualIngestService
from wp6_data.shared.upload_storage import UploadStorage

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent.parent
FILE_2024 = _REPO_ROOT / "Long_Data 2024.xlsx"
FILE_2025 = _REPO_ROOT / "Long_Data 2025.xlsx"

if not (FILE_2024.exists() and FILE_2025.exists()):
    pytest.skip(
        "real Long_Data .xlsx files not present (local-only smoke test)",
        allow_module_level=True,
    )


async def _purge(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM readings WHERE source = %s", (SOURCE,))
            await cur.execute(
                "DELETE FROM manual_uploads WHERE source = %s", (LONG_DATA.slug,),
            )
        await conn.commit()


@pytest_asyncio.fixture()
async def service(tmp_path):
    pool = AsyncConnectionPool(TSDB_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    await _purge(pool)
    storage = UploadStorage(base_dir=tmp_path, pool=pool)
    yield ManualIngestService(pool=pool, storage=storage, source=LONG_DATA)
    await _purge(pool)
    await pool.close()


async def _apply(service: ManualIngestService, path: Path) -> None:
    report = await service.validate(path.read_bytes())
    await service.apply(report.file_hash, path.name)


async def _years(pool: AsyncConnectionPool) -> set[int]:
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT DISTINCT EXTRACT(YEAR FROM time)::int AS y "
            "FROM readings WHERE source = %s",
            (SOURCE,),
        )
        return {r["y"] for r in await cur.fetchall()}


async def _count(pool: AsyncConnectionPool, source_filter: int) -> int:
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT COUNT(*) AS n FROM readings "
            "WHERE source = %s AND EXTRACT(YEAR FROM time) = %s",
            (SOURCE, source_filter),
        )
        return (await cur.fetchone())["n"]


@pytest.mark.asyncio
async def test_yearly_files_accumulate_under_one_source(service) -> None:
    """Ingesting 2024 then 2025 leaves both years present (scoped replace)."""
    pool = service.pool
    await _apply(service, FILE_2024)
    assert await _years(pool) == {2024}
    await _apply(service, FILE_2025)
    assert await _years(pool) == {2024, 2025}


@pytest.mark.asyncio
async def test_reingesting_a_year_leaves_other_years_untouched(service) -> None:
    pool = service.pool
    await _apply(service, FILE_2024)
    await _apply(service, FILE_2025)
    count_2024 = await _count(pool, 2024)
    count_2025 = await _count(pool, 2025)
    # Re-ingest 2025: its rows are replaced, 2024 is not touched.
    await _apply(service, FILE_2025)
    assert await _count(pool, 2024) == count_2024
    assert await _count(pool, 2025) == count_2025


@pytest.mark.asyncio
async def test_samples_stored_individually_not_meaned(service) -> None:
    """A high-sample group is stored as N rows, matching the decoder, not a
    single averaged value."""
    pool = service.pool
    await _apply(service, FILE_2024)
    # Pick the largest (device, date, sensor) group the decoder produced.
    groups: dict[tuple[str, date, str], int] = {}
    for r in parse(FILE_2024.read_bytes()):
        key = (r.device_name, r.time.date(), r.sensor_tag)
        groups[key] = groups.get(key, 0) + 1
    (device, day, sensor), expected = max(groups.items(), key=lambda kv: kv[1])
    assert expected > 1  # the source has multi-sample groups to preserve
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT COUNT(*) AS n FROM readings "
            "WHERE source = %s AND device_name = %s AND sensor_tag = %s "
            "AND time::date = %s",
            (SOURCE, device, sensor, day),
        )
        assert (await cur.fetchone())["n"] == expected
