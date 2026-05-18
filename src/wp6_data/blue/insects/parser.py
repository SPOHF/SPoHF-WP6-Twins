"""Parser for the blue insect-trap CSV dataset.

The source-specific half of the manual-ingest capability for blue: periodic
trap counts of total insects and *Drosophila suzukii* (spotted-wing
drosophila, a primary blueberry pest). The twin-agnostic data types and the
apply/audit/prune machinery are shared (``wp6_data.shared.manual_ingest``);
this module owns only the CSV reading, the column→sensor map, the single
synthetic device, and the local→UTC time conversion.

Mirrors the structural-vs-row-level split of the Sijia parser: a header
mismatch fast-fails with :class:`InsectParseError`; per-row dtype/timestamp
failures become :class:`SkippedRow` entries with reasons.
"""

import csv
import hashlib
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from wp6_data.shared.manual_ingest.types import (
    ManualParseError,
    Reading,
    SkippedRow,
    ValidationReport,
)

__all__ = [
    "COLUMN_TO_SENSOR",
    "DEVICE_KEY",
    "EXPECTED_HEADER",
    "LOCAL_TZ",
    "SOURCE",
    "TIMESTAMP_FORMAT",
    "InsectParseError",
    "Reading",
    "SkippedRow",
    "ValidationReport",
    "parse",
    "validate",
]

# Categorical value written to blue's `readings.project` column.
SOURCE = "insects"

# The CSV has no trap-discriminating column, so all rows belong to one
# synthetic device. Its human label/location lives in blue metadata.yaml,
# not here.
DEVICE_KEY = "insect-trap"

# Timestamps are timezone-naive wall-clock at the farm (the Netherlands).
# We localise DST-aware and convert to UTC server-side so insect counts share
# a time axis with the automated sensor data.
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
_UTC = ZoneInfo("UTC")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

COLUMN_TO_SENSOR: dict[str, str] = {
    "total_insects": "total_insects",
    # `suzukii` is empty in every current row; the parser skips empty cells,
    # so this sensor auto-activates when a future file populates it — no
    # schema or metadata change needed.
    "suzukii": "suzukii",
}

# Header compared exactly. Order matters.
EXPECTED_HEADER: tuple[str, ...] = ("timestamp", *COLUMN_TO_SENSOR.keys())

_TS_COL_IDX = EXPECTED_HEADER.index("timestamp")
_SENSOR_COL_INDICES: tuple[tuple[int, str], ...] = tuple(
    (EXPECTED_HEADER.index(col), sensor)
    for col, sensor in COLUMN_TO_SENSOR.items()
)


class InsectParseError(ManualParseError):
    """Insect CSV is structurally unparseable (wrong/missing header).

    Per-row failures are reported via ``ValidationReport.skipped_rows``
    rather than raised — only structural failures fast-fail. Subclasses the
    shared ManualParseError so the route factory renders a friendly
    rejection page for it.
    """


def _extract(file_bytes: bytes) -> tuple[list[Reading], list[SkippedRow], int]:
    """Validate the header, then return (readings, skipped, total_rows).

    Raises InsectParseError on a header/structure mismatch. ``utf-8-sig``
    strips a BOM if present; ``splitlines()`` makes the reader tolerant of
    CRLF, LF or CR endings.
    """
    text = file_bytes.decode("utf-8-sig")
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        raise InsectParseError("File is empty") from None

    actual_header = tuple(c.strip() for c in header)
    if actual_header != EXPECTED_HEADER:
        raise InsectParseError(
            f"Column headers mismatch. Expected {EXPECTED_HEADER!r}, "
            f"got {actual_header!r}"
        )

    buckets: dict[tuple[str, datetime, str], list[float]] = defaultdict(list)
    skipped: list[SkippedRow] = []
    total_rows = 0

    # start=2: header is line 1, so the first data row is line 2 — skipped-row
    # indices match what an admin sees opening the file.
    for line_idx, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue  # blank line — not a data row
        total_rows += 1

        if len(row) != len(EXPECTED_HEADER):
            skipped.append(SkippedRow(
                line_idx,
                f"expected {len(EXPECTED_HEADER)} columns, got {len(row)}",
            ))
            continue

        ts_raw = row[_TS_COL_IDX].strip()
        try:
            naive = datetime.strptime(ts_raw, TIMESTAMP_FORMAT)
        except ValueError:
            skipped.append(SkippedRow(
                line_idx,
                f"timestamp {ts_raw!r} is not {TIMESTAMP_FORMAT}",
            ))
            continue
        ts_utc = naive.replace(tzinfo=LOCAL_TZ).astimezone(_UTC)

        row_cells: list[tuple[str, float]] = []
        error: str | None = None
        for col_idx, sensor in _SENSOR_COL_INDICES:
            cell = row[col_idx].strip()
            if cell == "":
                continue  # empty cell → no reading (skips empty `suzukii`)
            try:
                value = float(cell)
            except ValueError:
                error = (
                    f"{EXPECTED_HEADER[col_idx]}: {cell!r} is not a number"
                )
                break
            row_cells.append((sensor, value))

        if error is not None:
            skipped.append(SkippedRow(line_idx, error))
            continue
        for sensor, value in row_cells:
            buckets[(DEVICE_KEY, ts_utc, sensor)].append(value)

    # Exact-duplicate timestamps are mean-bucketed: the file's duplicates are
    # exact-value duplicates so the mean preserves the value (a sum would
    # double it), and this also satisfies blue's unique (device, sensor, time)
    # dedup index.
    readings = [
        Reading(
            source=SOURCE,
            device_name=device,
            sensor_tag=sensor,
            time=ts,
            value=sum(values) / len(values),
        )
        for (device, ts, sensor), values in buckets.items()
    ]
    return readings, skipped, total_rows


def parse(file_bytes: bytes) -> list[Reading]:
    readings, _, _ = _extract(file_bytes)
    return readings


def validate(file_bytes: bytes) -> ValidationReport:
    readings, skipped, total_rows = _extract(file_bytes)

    devices = tuple(sorted({r.device_name for r in readings}))
    sensors = tuple(sorted({r.sensor_tag for r in readings}))
    if readings:
        dates = sorted({r.time.date() for r in readings})
        date_range: tuple[date, date] | None = (dates[0], dates[-1])
    else:
        date_range = None

    return ValidationReport(
        file_hash=hashlib.sha256(file_bytes).hexdigest(),
        file_size=len(file_bytes),
        total_rows=total_rows,
        valid_rows=total_rows - len(skipped),
        emitted_row_count=len(readings),
        skipped_rows=tuple(skipped),
        devices=devices,
        sensors=sensors,
        date_range=date_range,
    )
