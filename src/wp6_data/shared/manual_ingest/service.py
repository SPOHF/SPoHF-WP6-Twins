"""Generic transactional manual-ingest service.

Parameterised by ``(ManualSource, categorical-column-name, post-apply hook)``
so both twins share one apply path. Behaviour is identical to the original
red-only service; the only generalisations are: the categorical column name
({source} for red, {project} for blue) is injected rather than hardcoded to
``source``; the file suffix comes from the descriptor rather than ``.xlsx``;
and the post-apply cache-invalidation is an injected hook rather than a
hardcoded red import.

Two public methods:

- ``validate(file_bytes) -> ValidationReport`` — persist the file (idempotent
  on hash), run the source parser's validate, enrich with comparison facts.
- ``apply(validation_id, filename) -> ApplyResult`` — single transaction that
  atomically swaps the source's data: DELETE prior rows, INSERT the
  ``manual_uploads`` audit row, INSERT parsed readings; then post-commit
  bookkeeping + 2-file prune.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from wp6_data.db.queries import (
    record_sync_run,
    refresh_sensor_summary,
    upsert_daily_coverage,
)
from wp6_data.shared.manual_ingest.source import ManualSource
from wp6_data.shared.manual_ingest.types import ValidationReport
from wp6_data.shared.upload_storage import UploadStorage

logger = structlog.get_logger()

# Manual data is keyed by the `source` column on `readings` for *both* twins
# (red has it natively; blue gained it alongside its automated-view `project`
# column). The manual-ingest seam is therefore always `source` — no per-twin
# column parameter.
_COLUMN = "source"

PostApplyHook = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class ApplyResult:
    upload_id: int
    row_count: int


class ManualIngestService:
    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        storage: UploadStorage,
        source: ManualSource,
        post_apply_hook: PostApplyHook | None = None,
    ) -> None:
        self.pool = pool
        self.storage = storage
        self._source = source
        self._post_apply_hook = post_apply_hook

    @property
    def source(self) -> ManualSource:
        return self._source

    async def validate(self, file_bytes: bytes) -> ValidationReport:
        self.storage.write(
            self._source.slug, file_bytes, suffix=self._source.file_suffix,
        )
        report = self._source.validate(file_bytes)
        existing = await self._fetch_existing_facts()
        new_devices = set(report.devices)
        new_sensors = set(report.sensors)
        return replace(
            report,
            existing_row_count=existing["row_count"],
            existing_date_range=existing["date_range"],
            devices_removed=tuple(sorted(existing["devices"] - new_devices)),
            sensors_removed=tuple(sorted(existing["sensors"] - new_sensors)),
        )

    async def _fetch_existing_facts(self) -> dict:
        """Query the TSDB for the comparison facts the preview page surfaces."""
        value = self._source.categorical_value
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT COUNT(*) AS n, MIN(time)::date AS min_d, "
                f"MAX(time)::date AS max_d "
                f"FROM readings WHERE {_COLUMN} = %s",
                (value,),
            )
            counts = await cur.fetchone()
            await cur.execute(
                f"SELECT DISTINCT device_name FROM readings WHERE {_COLUMN} = %s",
                (value,),
            )
            devices = {r["device_name"] for r in await cur.fetchall()}
            await cur.execute(
                f"SELECT DISTINCT sensor_tag FROM readings WHERE {_COLUMN} = %s",
                (value,),
            )
            sensors = {r["sensor_tag"] for r in await cur.fetchall()}

        date_range: tuple[date, date] | None = (
            (counts["min_d"], counts["max_d"])
            if counts["min_d"] is not None
            else None
        )
        return {
            "row_count": counts["n"],
            "date_range": date_range,
            "devices": devices,
            "sensors": sensors,
        }

    async def apply(self, validation_id: str, filename: str) -> ApplyResult:
        """Apply the file at ``validation_id``, recording ``filename`` for provenance.

        Pass the human-meaningful original filename (the CLI's path name or
        the web form's ``UploadFile.filename``) — what's stored on disk is
        content-addressed by hash.
        """
        path = self.storage.path_for(
            self._source.slug, validation_id, self._source.file_suffix,
        )
        file_bytes = self.storage.read(path)
        readings = self._source.parse(file_bytes)

        value = self._source.categorical_value
        started = time.monotonic()
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"DELETE FROM readings WHERE {_COLUMN} = %s", (value,),
                )
                await cur.execute(
                    "INSERT INTO manual_uploads "
                    "(source, filename, file_hash, file_path, row_count) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (
                        self._source.slug,
                        filename,
                        validation_id,
                        str(path),
                        len(readings),
                    ),
                )
                upload_id = (await cur.fetchone())["id"]

                # Single multi-VALUES INSERT instead of executemany: psycopg3
                # would otherwise issue one round-trip per row (hundreds of
                # round-trips to TSDB exceeds the ingress timeout in prod).
                if readings:
                    placeholders = ", ".join(
                        ["(%s, %s, %s, %s, %s, %s)"] * len(readings),
                    )
                    flat_params: list = []
                    for r in readings:
                        flat_params.extend([
                            r.time, r.device_name, r.sensor_tag,
                            r.value, value, upload_id,
                        ])
                    await cur.execute(
                        f"INSERT INTO readings "
                        f"(time, device_name, sensor_tag, value, {_COLUMN}, "
                        f"upload_id) VALUES {placeholders}",
                        flat_params,
                    )
            await conn.commit()

        await self._post_apply_bookkeeping(readings, started)
        await self.storage.prune(self._source.slug)
        return ApplyResult(upload_id=upload_id, row_count=len(readings))

    async def _post_apply_bookkeeping(self, readings, started: float) -> None:
        """Refresh the cagg, upsert daily coverage, and audit the run.

        These run after the ingest transaction commits; each is wrapped so a
        bookkeeping failure cannot fail the upload itself (the data is
        already durably stored).
        """
        slug = self._source.slug
        coverage_records = [
            {
                "device_name": device,
                "sensor_tag": sensor,
                "day": day.isoformat(),
            }
            for device, sensor, day in {
                (r.device_name, r.sensor_tag, r.time.date()) for r in readings
            }
        ]
        max_time = max((r.time for r in readings), default=None)
        duration_sec = time.monotonic() - started

        try:
            async with self.pool.connection() as conn:
                await upsert_daily_coverage(conn, coverage_records)
                await record_sync_run(
                    conn,
                    slug,
                    success=True,
                    duration_sec=duration_sec,
                    records=len(readings),
                    last_timestamp=max_time,
                )
                await conn.commit()
        except Exception:
            logger.exception("manual_bookkeeping_failed", source=slug)

        try:
            await refresh_sensor_summary(self.pool)
        except Exception:
            logger.exception("manual_cagg_refresh_failed", source=slug)

        # In-process provider caches point at the cagg + coverage; the twin's
        # hook drops them so the next home/status request sees the just-written
        # rows instead of pre-upload stale data.
        if self._post_apply_hook is not None:
            result = self._post_apply_hook()
            if inspect.isawaitable(result):
                await result
