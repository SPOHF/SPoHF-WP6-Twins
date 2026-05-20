"""Shared parser scaffold.

Every manual source parses bytes the same way once the format is decoded:
collect one ``DecodedRow`` (or ``SkippedRow``) per source row, mean-bucket
``(device, time, sensor)`` so duplicate timestamps collapse deterministically,
then assemble a ``ValidationReport``. Only the *decoding* — Excel via
openpyxl, CSV with timezone conversion, … — is source-specific.

A source therefore supplies a single ``decode`` generator. ``bind`` turns it
into the ``parse`` / ``validate`` pair the ``ManualSource`` descriptor needs,
so per-source code is just "decode bytes → yield rows".
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

from wp6_data.shared.manual_ingest.types import (
    Reading,
    SkippedRow,
    ValidationReport,
)


@dataclass(frozen=True)
class DecodedRow:
    """One successfully-decoded source row, before aggregation.

    ``cells`` is the row's ``(sensor_tag, value)`` pairs; empty cells are
    simply omitted by the decoder (so an all-empty optional column emits no
    reading). The decoder is responsible for the source-specific timestamp
    (date defaulting, timezone conversion, …).
    """

    device_name: str
    time: datetime
    cells: tuple[tuple[str, float], ...]


# A decoder yields exactly one item per *data* row (DecodedRow for a good
# row, SkippedRow for a row-level failure); it raises ManualParseError for a
# structural failure (wrong header/sheet) before yielding. Blank/filler lines
# are dropped by the decoder without yielding, so they don't count as rows.
Decoder = Callable[[bytes], Iterator[DecodedRow | SkippedRow]]


def aggregate(
    categorical_value: str, decode: Decoder, file_bytes: bytes,
) -> tuple[list[Reading], list[SkippedRow], int]:
    """Run ``decode`` and mean-bucket its rows into ``Reading``s.

    ``total`` counts every source row (decoded or skipped) — identical
    semantics to the pre-extraction per-parser ``total_rows``.
    """
    buckets: dict[tuple[str, datetime, str], list[float]] = defaultdict(list)
    skipped: list[SkippedRow] = []
    total = 0
    for item in decode(file_bytes):
        total += 1
        if isinstance(item, SkippedRow):
            skipped.append(item)
            continue
        for sensor_tag, value in item.cells:
            buckets[(item.device_name, item.time, sensor_tag)].append(value)

    # Exact-duplicate (device, time, sensor) rows are mean-bucketed: the
    # file's duplicates are exact-value duplicates so the mean preserves the
    # value (a sum would double it), and it satisfies the unique dedup index.
    readings = [
        Reading(
            source=categorical_value,
            device_name=device,
            sensor_tag=sensor,
            time=ts,
            value=sum(values) / len(values),
        )
        for (device, ts, sensor), values in buckets.items()
    ]
    return readings, skipped, total


def build_report(
    file_bytes: bytes,
    readings: list[Reading],
    skipped: list[SkippedRow],
    total: int,
) -> ValidationReport:
    """Assemble the ``ValidationReport`` (identical across all sources)."""
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
        total_rows=total,
        valid_rows=total - len(skipped),
        emitted_row_count=len(readings),
        skipped_rows=tuple(skipped),
        devices=devices,
        sensors=sensors,
        date_range=date_range,
    )


def bind(
    categorical_value: str, decode: Decoder,
) -> tuple[Callable[[bytes], list[Reading]], Callable[[bytes], ValidationReport]]:
    """Build the ``(parse, validate)`` pair for a source from its decoder."""

    def parse(file_bytes: bytes) -> list[Reading]:
        readings, _, _ = aggregate(categorical_value, decode, file_bytes)
        return readings

    def validate(file_bytes: bytes) -> ValidationReport:
        readings, skipped, total = aggregate(
            categorical_value, decode, file_bytes,
        )
        return build_report(file_bytes, readings, skipped, total)

    return parse, validate
