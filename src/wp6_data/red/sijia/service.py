"""ManualIngestService: parser + UploadStorage + TSDB transactional apply.

Two public methods:

- ``validate(file_bytes) -> ValidationReport``
    Persists the file via UploadStorage (idempotent on hash), runs
    SijiaParser.validate, and (eventually — task 009-5) enriches the
    report with comparison facts against existing data.

- ``apply(validation_id) -> ApplyResult``
    Reads the file back by hash, parses, and executes the single
    transaction that swaps the source's data atomically: DELETE prior
    rows, INSERT manual_uploads audit row, INSERT parsed readings,
    then prune older files post-commit (issue 008).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from wp6_data.red.sijia.parser import SOURCE, ValidationReport, parse, validate
from wp6_data.shared.upload_storage import UploadStorage


@dataclass(frozen=True)
class ApplyResult:
    upload_id: int
    row_count: int


class ManualIngestService:
    SOURCE = SOURCE  # "sijia"

    def __init__(self, pool: AsyncConnectionPool, storage: UploadStorage) -> None:
        self.pool = pool
        self.storage = storage

    async def validate(self, file_bytes: bytes) -> ValidationReport:
        self.storage.write(self.SOURCE, file_bytes)
        report = validate(file_bytes)
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
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT COUNT(*) AS n, MIN(time)::date AS min_d, MAX(time)::date AS max_d "
                "FROM readings WHERE source = %s",
                (self.SOURCE,),
            )
            counts = await cur.fetchone()
            await cur.execute(
                "SELECT DISTINCT device_name FROM readings WHERE source = %s",
                (self.SOURCE,),
            )
            devices = {r["device_name"] for r in await cur.fetchall()}
            await cur.execute(
                "SELECT DISTINCT sensor_tag FROM readings WHERE source = %s",
                (self.SOURCE,),
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
        """Apply the file at validation_id, recording `filename` for provenance.

        Pass the human-meaningful original filename (e.g. ``sijia_seed.xlsx``
        from the CLI's path, or the ``UploadFile.filename`` from the web
        form) — what's stored on disk is content-addressed by hash.
        """
        path = self.storage.base_dir / self.SOURCE / f"{validation_id}.xlsx"
        file_bytes = self.storage.read(path)
        readings = parse(file_bytes)

        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "DELETE FROM readings WHERE source = %s", (self.SOURCE,),
                )
                await cur.execute(
                    "INSERT INTO manual_uploads "
                    "(source, filename, file_hash, file_path, row_count) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (
                        self.SOURCE,
                        filename,
                        validation_id,
                        str(path),
                        len(readings),
                    ),
                )
                upload_id = (await cur.fetchone())["id"]

                # Single multi-VALUES INSERT instead of executemany: psycopg3
                # would otherwise issue one round-trip per row (368+ round-trips
                # to TSDB exceeds the ingress timeout in prod).
                if readings:
                    placeholders = ", ".join(
                        ["(%s, %s, %s, %s, %s, %s)"] * len(readings),
                    )
                    flat_params: list = []
                    for r in readings:
                        flat_params.extend([
                            r.time, r.device_name, r.sensor_tag,
                            r.value, r.source, upload_id,
                        ])
                    await cur.execute(
                        "INSERT INTO readings "
                        "(time, device_name, sensor_tag, value, source, upload_id) "
                        f"VALUES {placeholders}",
                        flat_params,
                    )
            await conn.commit()

        await self.storage.prune(self.SOURCE)
        return ApplyResult(upload_id=upload_id, row_count=len(readings))
