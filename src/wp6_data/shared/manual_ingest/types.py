"""Twin-agnostic data types for the manual-ingest capability.

Each manual source parses its uploaded bytes into
``Reading``/``SkippedRow`` and reports a ``ValidationReport``. These types
carry no twin- or source-specific assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


class ManualParseError(Exception):
    """File is structurally unparseable (wrong sheet/header/shape).

    Per-row dtype failures are reported via ``ValidationReport.skipped_rows``
    rather than raised — only structural failures fast-fail. A source's
    decoder may subclass this so a route can render a friendly rejection
    page instead of a 500.
    """


@dataclass(frozen=True)
class Reading:
    """One parsed measurement, ready to INSERT into ``readings``.

    ``source`` is the parser's notion of the categorical value. The ingest
    service writes the descriptor's ``categorical_value`` into the readings
    ``source`` column, so this field is advisory provenance, not the
    authoritative routing key.
    """

    source: str
    device_name: str
    sensor_tag: str
    time: datetime
    value: float


@dataclass(frozen=True)
class SkippedRow:
    row_index: int  # 1-based, matching the source file's row numbering
    reason: str


@dataclass(frozen=True)
class ValidationReport:
    file_hash: str  # sha256 hex
    file_size: int  # bytes
    total_rows: int  # populated source rows (structural filler dropped)
    valid_rows: int  # source rows that survived dtype validation
    # Rows that will be INSERTed into ``readings`` on Apply. Differs from
    # valid_rows: one source row can emit many readings (one per non-empty
    # sensor cell) and rows sharing (device, time, sensor) are aggregated to
    # a single value. Compare this against ``existing_row_count`` for
    # regression detection.
    emitted_row_count: int = 0
    skipped_rows: tuple[SkippedRow, ...] = ()
    devices: tuple[str, ...] = ()  # sorted, distinct
    sensors: tuple[str, ...] = ()  # sorted, distinct
    date_range: tuple[date, date] | None = None  # None when no valid rows
    # Comparison facts vs. existing data for the same source. Populated by
    # ManualIngestService.validate(); parsers leave them at defaults.
    existing_row_count: int = 0
    existing_date_range: tuple[date, date] | None = None
    devices_removed: tuple[str, ...] = ()  # in existing, missing from new
    sensors_removed: tuple[str, ...] = ()  # in existing, missing from new
