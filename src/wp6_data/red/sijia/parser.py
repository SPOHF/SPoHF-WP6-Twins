"""Parser for the Sijia (Neurath) seasonal greenhouse Excel dataset."""

import hashlib
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

SOURCE = "sijia"
SHEET_NAME = "2025-26_Measurement"

META_COLUMNS: tuple[str, ...] = ("Sample No.", "Variety", "Block", "Row", "Date")

COLUMN_TO_SENSOR: dict[str, str] = {
    "ChlM": "chlorophyll",
    "FlvM": "flavonoids",
    "AnthM": "anthocyanins",
    "NFI": "nfi",
    "Water Content (% of weight)": "water_content",
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

# Sensors whose Excel value is a 0..1 fraction; parser scales to percentage
# so Y-axes are consistent with sensor data conventions (e.g. humidity %RH).
PERCENTAGE_SENSORS: frozenset[str] = frozenset({"water_content", "minerals"})


class SijiaParseError(Exception):
    """File is structurally unparseable (wrong sheet, wrong headers).

    Per-row dtype failures are reported via ValidationReport.skipped_rows
    rather than raised — only structural failures fast-fail.
    """


@dataclass(frozen=True)
class Reading:
    source: str
    device_name: str
    sensor_tag: str
    time: datetime
    value: float


@dataclass(frozen=True)
class SkippedRow:
    row_index: int  # 1-based, matching Excel row numbering
    reason: str


@dataclass(frozen=True)
class ValidationReport:
    file_hash: str  # sha256 hex
    file_size: int  # bytes
    total_rows: int  # populated source rows (NaN-Date filler dropped)
    valid_rows: int  # source rows that survived dtype validation
    skipped_rows: tuple[SkippedRow, ...]
    devices: tuple[str, ...]  # sorted, distinct
    sensors: tuple[str, ...]  # sorted, distinct
    date_range: tuple[date, date] | None  # None when no valid rows


def _device_name(variety: str, block: str, row: float) -> str:
    return f"neurath-{block}-{int(row)}-{variety.strip().lower()}"


def _extract(file_bytes: bytes) -> tuple[list[Reading], list[SkippedRow], int]:
    """Shared pipeline. Validates structure, then returns (readings, skipped, total_rows).

    Raises SijiaParseError if the sheet or column headers don't match expectations.
    Per-row dtype failures are collected into `skipped`, not raised.
    """
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    if SHEET_NAME not in xl.sheet_names:
        raise SijiaParseError(
            f"Required sheet {SHEET_NAME!r} not found; file contains {xl.sheet_names!r}"
        )
    df = pd.read_excel(xl, sheet_name=SHEET_NAME)
    if tuple(df.columns) != EXPECTED_HEADERS:
        raise SijiaParseError(
            f"Column headers mismatch. Expected {EXPECTED_HEADERS!r}, got {tuple(df.columns)!r}"
        )

    df = df.dropna(subset=["Date"])
    total_rows = len(df)

    buckets: dict[tuple[str, datetime, str], list[float]] = defaultdict(list)
    skipped: list[SkippedRow] = []

    for idx, r in df.iterrows():
        excel_row = int(idx) + 2  # +1 for 1-based, +1 for the header row
        device = _device_name(r["Variety"], r["Block"], r["Row"])
        time = r["Date"].to_pydatetime()

        row_cells: list[tuple[str, float]] = []
        error: str | None = None
        for column, sensor in COLUMN_TO_SENSOR.items():
            value = r[column]
            if pd.isna(value):
                continue
            try:
                scaled = float(value) * 100 if sensor in PERCENTAGE_SENSORS else float(value)
            except (TypeError, ValueError):
                error = f"{column}: {value!r} is not a number"
                break
            row_cells.append((sensor, scaled))

        if error is not None:
            skipped.append(SkippedRow(row_index=excel_row, reason=error))
            continue
        for sensor, scaled in row_cells:
            buckets[(device, time, sensor)].append(scaled)

    readings = [
        Reading(
            source=SOURCE,
            device_name=device,
            sensor_tag=sensor,
            time=time,
            value=sum(values) / len(values),
        )
        for (device, time, sensor), values in buckets.items()
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
        skipped_rows=tuple(skipped),
        devices=devices,
        sensors=sensors,
        date_range=date_range,
    )
