"""Blue fertigation-events CSV source.

Parses farm fertigation schedules from CSV into manual-ingest ``Reading`` rows,
keeping the existing columns and upload UX conventions used by other Blue
manual sources. Rows are keyed by treatment code (fallback: treatment name)
and emit numeric readings for ``program_id``, ``volume_ml_per_plant`` and
``duration_min`` when present.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from wp6_data.shared.manual_ingest import (
    ManualParseError,
    ManualSource,
    Reading,
    SkippedRow,
    ValidationReport,
)
from wp6_data.shared.manual_ingest.parsing import build_report

SOURCE = "fertigation_events"

EXPECTED_HEADER: tuple[str, ...] = (
    "date",
    "program_id",
    "treatment_code",
    "treatment_name",
    "volume_ml_per_plant",
    "duration_min",
    "remarks",
)


class FertigationEventsParseError(ManualParseError):
    """Fertigation CSV is structurally unparseable (wrong/missing header)."""


def _aggregate(file_bytes: bytes) -> tuple[list[Reading], list[SkippedRow], int]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise FertigationEventsParseError("File is empty") from None

    actual_header = tuple(c.strip() for c in header)
    if actual_header != EXPECTED_HEADER:
        raise FertigationEventsParseError(
            f"Column headers mismatch. Expected {EXPECTED_HEADER!r}, "
            f"got {actual_header!r}"
        )

    skipped: list[SkippedRow] = []
    rows: list[tuple[str, date, float | None, float | None, float | None]] = []
    total = 0

    for line_idx, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue

        if len(row) != len(EXPECTED_HEADER):
            skipped.append(
                SkippedRow(
                    line_idx,
                    f"expected {len(EXPECTED_HEADER)} columns, got {len(row)}",
                )
            )
            total += 1
            continue

        day_raw = row[0].strip()
        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            skipped.append(SkippedRow(line_idx, f"date {day_raw!r} is not YYYY-MM-DD"))
            total += 1
            continue

        treatment_code = row[2].strip()
        treatment_name = row[3].strip()
        device = treatment_code or treatment_name
        if not device:
            skipped.append(
                SkippedRow(line_idx, "treatment_code and treatment_name are both empty")
            )
            total += 1
            continue

        def _parse_float(raw: str, col: str) -> float | None:
            v = raw.strip()
            if v == "":
                return None
            import math
            try:
                num = float(v)
            except ValueError as exc:
                raise ValueError(f"{col}: {raw!r} is not a number") from exc
            if not math.isfinite(num):
                raise ValueError(f"{col}: {raw!r} is not a finite number")
            return num
        try:
            program_id = _parse_float(row[1], "program_id")
            volume = _parse_float(row[4], "volume_ml_per_plant")
            duration = _parse_float(row[5], "duration_min")
        except ValueError as exc:
            skipped.append(SkippedRow(line_idx, str(exc)))
            total += 1
            continue

        total += 1
        rows.append((device, day, program_id, volume, duration))

    ordinal: dict[tuple[str, date], int] = defaultdict(int)
    readings: list[Reading] = []
    for device, day, program_id, volume, duration in rows:
        key = (device, day)
        ordinal[key] += 1
        ts = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(
            seconds=ordinal[key],
        )
        if program_id is not None:
            readings.append(
                Reading(
                    source=SOURCE,
                    device_name=device,
                    sensor_tag="program_id",
                    time=ts,
                    value=program_id,
                )
            )
        if volume is not None:
            readings.append(
                Reading(
                    source=SOURCE,
                    device_name=device,
                    sensor_tag="volume_ml_per_plant",
                    time=ts,
                    value=volume,
                )
            )
        if duration is not None:
            readings.append(
                Reading(
                    source=SOURCE,
                    device_name=device,
                    sensor_tag="duration_min",
                    time=ts,
                    value=duration,
                )
            )

    return readings, skipped, total


def parse(file_bytes: bytes) -> list[Reading]:
    return _aggregate(file_bytes)[0]


def validate(file_bytes: bytes) -> ValidationReport:
    readings, skipped, total = _aggregate(file_bytes)
    return build_report(file_bytes, readings, skipped, total)


FERTIGATION_EVENTS = ManualSource(
    slug="fertigation_events",
    categorical_value=SOURCE,
    display_name="Fertigation events",
    file_suffix=".csv",
    accept=".csv,text/csv",
    row_noun="CSV rows",
    upload_hint=(
        "Upload a fertigation events .csv file "
        "(columns: date,program_id,treatment_code,treatment_name,"
        "volume_ml_per_plant,duration_min,remarks)."
    ),
    parse=parse,
    validate=validate,
    parse_error=FertigationEventsParseError,
)
