"""Parser for the Sijia (Neurath) seasonal greenhouse Excel dataset.

This is the source-specific half of the manual-ingest capability: the
Excel/openpyxl reading, the Sijia column→sensor map, the Neurath device
naming, and the percentage scaling. The twin-agnostic data types
(``Reading``/``SkippedRow``/``ValidationReport``) and the base parse error
now live in ``wp6_data.shared.manual_ingest`` and are re-exported here so the
existing Sijia parser test suite and importers are unaffected.
"""

import io
from collections.abc import Iterator
from datetime import datetime, time

import openpyxl
from openpyxl.utils import get_column_letter

from wp6_data.shared.manual_ingest.parsing import DecodedRow, bind
from wp6_data.shared.manual_ingest.types import (
    ManualParseError,
    Reading,
    SkippedRow,
    ValidationReport,
)

__all__ = [
    "COLUMN_TO_SENSOR",
    "DEFAULT_MEASUREMENT_HOUR",
    "EXPECTED_HEADERS",
    "META_COLUMNS",
    "PERCENTAGE_SENSORS",
    "SHEET_NAME",
    "SOURCE",
    "Reading",
    "SijiaParseError",
    "SkippedRow",
    "ValidationReport",
    "parse",
    "validate",
]

SOURCE = "sijia"
SHEET_NAME = "2025-26_Measurement"

# Excel rows record only a date, no time of day. Anchor measurements at 13:00
# so charts plot them at a sensible mid-day point (and so all readings from a
# single visit cluster at the same instant per (device, sensor)).
DEFAULT_MEASUREMENT_HOUR = 13

META_COLUMNS: tuple[str, ...] = ("Sample No.", "Variety", "Block", "Row", "Date")

COLUMN_TO_SENSOR: dict[str, str] = {
    "ChlM": "chlorophyll",
    "FlvM": "flavonoids",
    "AnthM": "anthocyanins",
    "NFI": "nfi",
    "Water Content (% of weight)": "water_content",
    # Trailing space is Sijia's, and the header match is exact — keep it.
    "umgerechnete °Brix ": "brix",
    "Minerals (% of weight)": "minerals",
    "Size Ø (mm)": "diameter",
    "Weight (g)": "weight",
    "Vitamin C – Fresh Sample (mg/100 g)": "vitamin_c_fresh",
    "Vitamin C – Dry Matter (mg/100 g)": "vitamin_c_dry",
    "Total Phenols – Fresh Sample (mg GAE/100 g)": "total_phenols_fresh",
    "Total Phenols – Dry Matter (mg GAE/100 g)": "total_phenols_dry",
    "Antioxidant Capacity – Fresh Sample (mmol TAE/100 g)": "antioxidant_capacity_fresh",
    "Antioxidant Capacity – Dry Matter (mmol TAE/100 g)": "antioxidant_capacity_dry",
}

# Headers compared exactly (em-dash sensitive). Order matters.
EXPECTED_HEADERS: tuple[str, ...] = META_COLUMNS + tuple(COLUMN_TO_SENSOR.keys())

# Sensors whose Excel value is a 0..1 fraction; parser scales to per-100 units
# so Y-axes are consistent with sensor data conventions (e.g. humidity %RH).
# °Brix is a g-per-100-g mass fraction, so it takes the same scaling.
PERCENTAGE_SENSORS: frozenset[str] = frozenset(
    {"water_content", "minerals", "brix"}
)


class SijiaParseError(ManualParseError):
    """Sijia file is structurally unparseable (wrong sheet, wrong headers).

    Per-row dtype failures are reported via ValidationReport.skipped_rows
    rather than raised — only structural failures fast-fail. Subclasses the
    shared ManualParseError so the shared route factory can render a friendly
    rejection page for it.
    """


def _device_name(variety: str, block: str, row: float) -> str:
    return f"neurath-{block}-{int(row)}-{variety.strip().lower()}"


_DATE_COL_IDX = EXPECTED_HEADERS.index("Date")
_VARIETY_COL_IDX = EXPECTED_HEADERS.index("Variety")
_BLOCK_COL_IDX = EXPECTED_HEADERS.index("Block")
_ROW_COL_IDX = EXPECTED_HEADERS.index("Row")
_SENSOR_COL_INDICES: tuple[tuple[int, str], ...] = tuple(
    (EXPECTED_HEADERS.index(col), sensor)
    for col, sensor in COLUMN_TO_SENSOR.items()
)


# Long mismatch lists (a wholly wrong file) are truncated so the rejection
# page stays readable; the first few names are enough to identify the problem.
_MAX_LISTED_COLUMNS = 5


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:_MAX_LISTED_COLUMNS])
    extra = len(items) - _MAX_LISTED_COLUMNS
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def _strip_trailing_blanks(header_row: tuple) -> tuple:
    """Header cells with Excel's trailing empty padding removed.

    Excel reports styled-but-empty cells past the last real column, and in
    read_only mode openpyxl trusts the sheet's declared dimension, so a raw
    comparison would reject a good file over padding alone. Only *trailing*
    blanks are dropped — an added column in the middle survives and gets
    reported, which a truncating slice would have silently swallowed.
    """
    cells = list(header_row)
    while cells and (cells[-1] is None or str(cells[-1]).strip() == ""):
        cells.pop()
    return tuple(cells)


def _describe_header_mismatch(actual: tuple) -> str:
    """Explain a header mismatch in terms a spreadsheet author can act on.

    Names the columns that were added (with their Excel letter) and removed,
    rather than dumping two ~20-column tuples the reader has to diff by eye.
    """
    unexpected = [
        f"{get_column_letter(idx + 1)} {cell!r}"
        for idx, cell in enumerate(actual)
        if cell not in EXPECTED_HEADERS
    ]
    missing = [repr(h) for h in EXPECTED_HEADERS if h not in actual]

    parts: list[str] = []
    if unexpected:
        parts.append(f"unexpected: {_listed(unexpected)}")
    if missing:
        parts.append(f"missing: {_listed(missing)}")
    if not parts:
        # Same names, so the columns were reordered — point at the first
        # position that diverges.
        # strict=False: a duplicated name can leave the lengths unequal
        # even when both headers carry the same set of names.
        pairs = zip(actual, EXPECTED_HEADERS, strict=False)
        for idx, (got, want) in enumerate(pairs):
            if got != want:
                parts.append(
                    f"out of order at column {get_column_letter(idx + 1)}: "
                    f"expected {want!r}, got {got!r}"
                )
                break
    if not parts:  # e.g. a duplicated column name; fall back to the raw header
        parts.append(f"got {actual!r}")

    return (
        f"Column headers mismatch in sheet {SHEET_NAME!r} "
        f"({len(actual)} columns, expected {len(EXPECTED_HEADERS)}) — "
        + "; ".join(parts)
    )


def _decode(file_bytes: bytes) -> Iterator[DecodedRow | SkippedRow]:
    """Decode the Sijia workbook into one row per measurement.

    The only Sijia-specific code: structural validation, the Neurath device
    naming, the date→13:00 anchoring and the percentage scaling. Bucketing,
    mean-aggregation and the ValidationReport are the shared scaffold.

    Implementation note: openpyxl in read_only mode is used directly rather
    than pandas read_excel because the Sijia file routinely carries 6+
    extra sheets (Klima, Pivot, Diagram) that bloat the workbook to 15 MB+.
    pandas would parse all of them and iterate the worksheet's full padded
    1,048,576-row dimension; openpyxl's streaming reader plus an early
    break on a NULL Date column reads only the actual ~120 measurement rows.
    """
    wb = openpyxl.load_workbook(
        io.BytesIO(file_bytes), read_only=True, data_only=True,
    )
    try:
        if SHEET_NAME not in wb.sheetnames:
            raise SijiaParseError(
                f"Required sheet {SHEET_NAME!r} not found; "
                f"file contains {wb.sheetnames!r}"
            )
        ws = wb[SHEET_NAME]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise SijiaParseError(f"Sheet {SHEET_NAME!r} is empty") from None

        actual_headers = _strip_trailing_blanks(header_row)
        if actual_headers != EXPECTED_HEADERS:
            raise SijiaParseError(_describe_header_mismatch(actual_headers))

        for excel_idx, raw_row in enumerate(rows_iter, start=2):
            # First all-empty / NULL-Date row marks end of measurements;
            # Excel pads worksheets to 1,048,576 rows that we must NOT iterate.
            if raw_row[_DATE_COL_IDX] is None:
                break

            variety = raw_row[_VARIETY_COL_IDX]
            block = raw_row[_BLOCK_COL_IDX]
            row_num = raw_row[_ROW_COL_IDX]
            device = _device_name(variety, block, row_num)

            ts = raw_row[_DATE_COL_IDX]
            if not isinstance(ts, datetime):
                ts = datetime.combine(ts, time(0, 0))
            if ts.time() == time(0, 0):
                ts = ts.replace(hour=DEFAULT_MEASUREMENT_HOUR)

            row_cells: list[tuple[str, float]] = []
            error: str | None = None
            for col_idx, sensor in _SENSOR_COL_INDICES:
                value = raw_row[col_idx]
                if value is None:
                    continue
                try:
                    scaled = (
                        float(value) * 100 if sensor in PERCENTAGE_SENSORS
                        else float(value)
                    )
                except (TypeError, ValueError):
                    error = f"{EXPECTED_HEADERS[col_idx]}: {value!r} is not a number"
                    break
                row_cells.append((sensor, scaled))

            if error is not None:
                yield SkippedRow(row_index=excel_idx, reason=error)
            else:
                yield DecodedRow(
                    device_name=device, time=ts, cells=tuple(row_cells),
                )
    finally:
        wb.close()


parse, validate = bind(SOURCE, _decode)
