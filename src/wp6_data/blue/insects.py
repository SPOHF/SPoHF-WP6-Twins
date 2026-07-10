"""Blue insect-trap CSV source — the only insect-specific code.

`insects` is the blue twin's first manual data source: periodic trap counts
of total insects and *Drosophila suzukii* (spotted-wing drosophila, a primary
blueberry pest). Everything generic — storage, transactional apply, audit,
prune, the preview/apply/history UI, the CLI, and the parser scaffold
(mean-bucketing + ValidationReport) — lives in
``wp6_data.shared.manual_ingest`` and the blue twin's generic manual glue
(``wp6_data.blue.manual``). This module is just the CSV decoder + the
``ManualSource`` descriptor.

Structural-vs-row-level split: a header mismatch fast-fails with
:class:`InsectParseError`; per-row dtype/timestamp failures become
:class:`SkippedRow` entries with reasons.
"""

import csv
from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

from wp6_data.shared.manual_ingest import (
    DecodedRow,
    ManualParseError,
    ManualSource,
    SkippedRow,
    bind,
)

# Categorical value written to blue's `readings.source` column.
SOURCE = "insects"

# The CSV has no trap-discriminating column, so all rows belong to one
# synthetic device. Its human label/location lives in blue metadata.yaml.
DEVICE_KEY = "insect-trap"

# Timestamps are timezone-naive wall-clock at the farm (the Netherlands).
# Localise DST-aware and convert to UTC server-side so insect counts share a
# time axis with the automated sensor data.
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
_UTC = ZoneInfo("UTC")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

COLUMN_TO_SENSOR: dict[str, str] = {
    "total_insects": "total_insects",
    # `suzukii` is empty in every current row; empty cells emit no reading,
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

    Per-row failures are reported via skipped rows rather than raised — only
    structural failures fast-fail. Subclasses the shared ManualParseError so
    the route factory renders a friendly rejection page.
    """


def _decode(file_bytes: bytes) -> Iterator[DecodedRow | SkippedRow]:
    """Decode the insect CSV into one row per data line.

    The only insect-specific code: the exact-header check, the single
    synthetic device, and the DST-aware Europe/Amsterdam→UTC conversion.
    Bucketing, mean-aggregation and the ValidationReport are shared.

    ``utf-8-sig`` strips a BOM if present; ``splitlines()`` makes the reader
    tolerant of CRLF, LF or CR endings.
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

    # start=2: header is line 1, so the first data row is line 2 — skipped-row
    # indices match what an admin sees opening the file.
    for line_idx, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue  # blank line — not a data row

        if len(row) != len(EXPECTED_HEADER):
            yield SkippedRow(
                line_idx,
                f"expected {len(EXPECTED_HEADER)} columns, got {len(row)}",
            )
            continue

        ts_raw = row[_TS_COL_IDX].strip()
        try:
            naive = datetime.strptime(ts_raw, TIMESTAMP_FORMAT)
        except ValueError:
            yield SkippedRow(
                line_idx,
                f"timestamp {ts_raw!r} is not {TIMESTAMP_FORMAT}",
            )
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
                error = f"{EXPECTED_HEADER[col_idx]}: {cell!r} is not a number"
                break
            row_cells.append((sensor, value))

        if error is not None:
            yield SkippedRow(line_idx, error)
        else:
            yield DecodedRow(
                device_name=DEVICE_KEY, time=ts_utc, cells=tuple(row_cells),
            )


parse, validate = bind(SOURCE, _decode)

INSECTS = ManualSource(
    slug="insects",
    categorical_value=SOURCE,
    display_name="Insect traps",
    file_suffix=".csv",
    accept=".csv,text/csv",
    row_noun="CSV rows",
    upload_hint=(
        "Upload an insect-trap counts .csv file "
        "(header: timestamp,total_insects,suzukii)."
    ),
    parse=parse,
    validate=validate,
    parse_error=InsectParseError,
)
