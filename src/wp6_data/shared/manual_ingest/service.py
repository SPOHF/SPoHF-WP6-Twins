"""Generic transactional manual-ingest service.

Parameterised by ``(ManualSource, post-apply hook)`` so every twin and
source shares one apply path. Manual data is always keyed by the readings
``source`` column; the file suffix comes from the descriptor; and the
post-apply cache-invalidation is an injected hook. The service knows
nothing about which twin or source it is serving.

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
)
from wp6_data.shared.manual_ingest.source import ManualSource
from wp6_data.shared.manual_ingest.types import ValidationReport
from wp6_data.shared.upload_storage import UploadStorage

logger = structlog.get_logger()

# Manual data is always keyed by the `source` column on `readings`. The
# seam is therefore a constant, not a per-twin/per-source parameter.
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
        existing = await self._fetch_existing_facts(report.date_range)
        new_devices = set(report.devices)
        new_sensors = set(report.sensors)
        return replace(
            report,
            existing_row_count=existing["row_count"],
            existing_date_range=existing["date_range"],
            devices_removed=tuple(sorted(existing["devices"] - new_devices)),
            sensors_removed=tuple(sorted(existing["sensors"] - new_sensors)),
        )

    def _scope_clause(
        self, date_range: tuple[date, date] | None,
    ) -> tuple[str, list]:
        """Extra WHERE fragment narrowing replace/compare to the upload's scope.

        Whole-source by default (empty clause). A source with a ``replace_scope``
        narrows it to part of its rows (e.g. long_data restricts to the calendar
        years in the file) so one source fed by yearly files replaces only the
        uploaded year. A scoped source with an empty upload matches nothing
        (``1=0``) rather than wiping the whole source.
        """
        if self._source.replace_scope is None:
            return "", []
        if date_range is None:
            return " AND 1=0", []
        return self._source.replace_scope(date_range)

    async def _fetch_existing_facts(
        self, date_range: tuple[date, date] | None = None,
    ) -> dict:
        """Query the TSDB for the comparison facts the preview page surfaces.

        Scoped to the same rows the apply will replace, so a single-year
        upload does not report every other year's devices/sensors as removed.
        """
        value = self._source.categorical_value
        clause, sparams = self._scope_clause(date_range)
        params = [value, *sparams]
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT COUNT(*) AS n, MIN(time)::date AS min_d, "
                f"MAX(time)::date AS max_d "
                f"FROM readings WHERE {_COLUMN} = %s{clause}",
                params,
            )
            counts = await cur.fetchone()
            await cur.execute(
                f"SELECT DISTINCT device_name FROM readings "
                f"WHERE {_COLUMN} = %s{clause}",
                params,
            )
            devices = {r["device_name"] for r in await cur.fetchall()}
            await cur.execute(
                f"SELECT DISTINCT sensor_tag FROM readings "
                f"WHERE {_COLUMN} = %s{clause}",
                params,
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
        # Replace only the rows in this upload's scope (whole-source unless the
        # source narrows it — see `_scope_clause`). Derived from the parsed
        # readings so it matches exactly what is about to be inserted.
        dates = [r.time.date() for r in readings]
        scope_range = (min(dates), max(dates)) if dates else None
        clause, sparams = self._scope_clause(scope_range)
        started = time.monotonic()
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"DELETE FROM readings WHERE {_COLUMN} = %s{clause}",
                    [value, *sparams],
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
        """Refresh the cagg and audit the run.

        These run after the ingest transaction commits; each is wrapped so a
        bookkeeping failure cannot fail the upload itself (the data is
        already durably stored). Coverage is derived from the cagg, so the
        refresh below is what makes the just-uploaded days visible on /status.
        """
        slug = self._source.slug
        max_time = max((r.time for r in readings), default=None)
        duration_sec = time.monotonic() - started

        try:
            async with self.pool.connection() as conn:
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

        # In-process provider caches point at the cagg; the twin's hook drops
        # them so the next home/status request sees the just-written rows
        # instead of pre-upload stale data.
        if self._post_apply_hook is not None:
            result = self._post_apply_hook()
            if inspect.isawaitable(result):
                await result
