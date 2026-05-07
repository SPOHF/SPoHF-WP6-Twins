"""Tests for the Sijia (Neurath) Excel parser."""

from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from wp6_data.red.sijia.parser import (
    COLUMN_TO_SENSOR,
    DEFAULT_MEASUREMENT_HOUR,
    EXPECTED_HEADERS,
    SHEET_NAME,
    SOURCE,
    SijiaParseError,
    parse,
    validate,
)

SEED_PATH = Path(__file__).parent / "fixtures" / "sijia_seed.xlsx"


def _xlsx_bytes(sheet_name: str, headers: list[str], rows: list[list]) -> bytes:
    """Build a minimal in-memory xlsx file for negative-path tests."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def seed_bytes() -> bytes:
    return SEED_PATH.read_bytes()


@pytest.fixture(scope="module")
def seed_readings(seed_bytes) -> list:
    return parse(seed_bytes)


def test_parse_seed_returns_readings_tagged_with_source_sijia(seed_readings) -> None:
    readings = seed_readings

    assert len(readings) > 0
    assert all(r.source == SOURCE for r in readings)


def test_parse_defaults_missing_time_to_one_pm(seed_readings) -> None:
    """Excel rows in the seed have only a date (time = 00:00). The parser
    fills that gap with a sensible mid-day default so charts don't bunch
    all measurements at midnight."""
    assert all(r.time.hour == DEFAULT_MEASUREMENT_HOUR for r in seed_readings)
    assert all(r.time.minute == 0 for r in seed_readings)
    assert all(r.time.second == 0 for r in seed_readings)


def test_parse_preserves_explicit_time_when_present() -> None:
    """If a future Excel row has a real measurement time, the parser keeps it
    — only midnight (the Excel default for date-only cells) is gap-filled."""
    headers = list(EXPECTED_HEADERS)
    # Row with an explicit measurement time of 09:30
    row = [1, "TestVariety", "B", 2034, datetime(2025, 8, 7, 9, 30)] + [
        None
    ] * len(COLUMN_TO_SENSOR)
    # Put a value in the first sensor column so the row produces a Reading
    row[len(("Sample No.", "Variety", "Block", "Row", "Date"))] = 0.5

    xlsx = _xlsx_bytes(SHEET_NAME, headers, [row])
    readings = parse(xlsx)

    assert readings, "expected at least one Reading from the test row"
    assert all(r.time.hour == 9 and r.time.minute == 30 for r in readings)


def test_parse_emits_neurath_block_row_variety_device_names(seed_readings) -> None:
    readings = seed_readings
    devices = {r.device_name for r in readings}

    assert "neurath-B-2034-strabelina" in devices
    assert "neurath-B-2012-shivious" in devices


def test_parse_maps_chlm_column_to_chlorophyll_sensor_tag(seed_readings) -> None:
    readings = seed_readings
    sensors = {r.sensor_tag for r in readings}

    assert "chlorophyll" in sensors


def test_parse_aggregates_same_date_plant_sensor_to_mean(seed_readings) -> None:
    readings = seed_readings

    # Seed has 4 ChlM samples for Strabelina @ B-2034 on 2025-08-07:
    chlm_samples = [0.583333, 0.553333, 0.563333, 0.720000]
    matches = [
        r
        for r in readings
        if r.device_name == "neurath-B-2034-strabelina"
        and r.sensor_tag == "chlorophyll"
        and r.time.date() == date(2025, 8, 7)
    ]

    assert len(matches) == 1
    assert matches[0].value == pytest.approx(sum(chlm_samples) / len(chlm_samples))


def test_parse_scales_water_content_fraction_to_percentage(seed_readings) -> None:
    # Seed Water Content samples for Strabelina @ B-2034 on 2025-08-07
    # are stored as fractions (0.9391, 0.9444, 0.9394, 0.9397).
    # Parser must scale to percentage so chart Y-axes match humidity (%RH).
    raw_samples = [0.9391, 0.9444, 0.9394, 0.9397]
    expected_pct = sum(raw_samples) / len(raw_samples) * 100

    matches = [
        r
        for r in seed_readings
        if r.device_name == "neurath-B-2034-strabelina"
        and r.sensor_tag == "water_content"
        and r.time.date() == date(2025, 8, 7)
    ]

    assert len(matches) == 1
    assert matches[0].value == pytest.approx(expected_pct)


def test_parse_drops_nan_weight_cells_without_emitting_zero(seed_readings) -> None:
    # All 4 Weight (g) samples for Strabelina @ B-2034 on 2025-08-07 are NaN.
    # All 4 Weight (g) samples for Shivious @ B-2012 on 2025-10-02 are filled.
    nan_group = [
        r
        for r in seed_readings
        if r.device_name == "neurath-B-2034-strabelina"
        and r.sensor_tag == "weight"
        and r.time.date() == date(2025, 8, 7)
    ]
    filled_group = [
        r
        for r in seed_readings
        if r.device_name == "neurath-B-2012-shivious"
        and r.sensor_tag == "weight"
        and r.time.date() == date(2025, 10, 2)
    ]

    assert nan_group == []  # NaN cells must not appear (and must not be zeroed)
    assert len(filled_group) == 1
    assert filled_group[0].value == pytest.approx(39.55375)


def test_validate_seed_returns_report_with_file_facts(seed_bytes) -> None:
    report = validate(seed_bytes)

    # File-level facts
    assert len(report.file_hash) == 64
    assert all(c in "0123456789abcdef" for c in report.file_hash)
    assert report.file_size == len(seed_bytes)

    # Row counts (seed has 112 populated rows, all dtype-valid)
    assert report.total_rows == 112
    assert report.valid_rows == 112
    assert report.skipped_rows == ()

    # Distinct devices and sensors derived from emitted readings
    assert "neurath-B-2034-strabelina" in report.devices
    assert "neurath-B-2012-shivious" in report.devices
    assert "chlorophyll" in report.sensors

    # Date range covers the populated data
    assert report.date_range == (date(2025, 8, 7), date(2026, 4, 16))


def test_validate_raises_on_wrong_sheet_name() -> None:
    bad = _xlsx_bytes("NotTheRightSheet", ["Date"], [["2025-01-01"]])

    with pytest.raises(SijiaParseError):
        validate(bad)


def test_validate_raises_when_em_dash_header_is_replaced_with_hyphen() -> None:
    # Researcher recreates the file in a different locale; autocorrect
    # replaces the en-dash 'Vitamin C – Fresh Sample' (U+2013) with a
    # plain hyphen-minus 'Vitamin C - Fresh Sample' (U+002D). Parser
    # must catch this drift rather than silently skipping the column.
    bad_headers = list(EXPECTED_HEADERS)
    vitamin_c_fresh_index = bad_headers.index("Vitamin C – Fresh Sample (mg/100 g)")
    bad_headers[vitamin_c_fresh_index] = bad_headers[vitamin_c_fresh_index].replace("–", "-")
    bad = _xlsx_bytes(SHEET_NAME, bad_headers, [])

    with pytest.raises(SijiaParseError):
        validate(bad)


def test_validate_reports_rows_with_non_numeric_sensor_values_as_skipped() -> None:
    sensor_count = len(COLUMN_TO_SENSOR)
    sample_date = datetime(2025, 8, 7)
    rows = [
        # Row 2 (Excel-numbered): all cells valid
        ["S1", "Strabelina ", "B", 2034, sample_date, *([0.5] * sensor_count)],
        # Row 3: ChlM cell is non-numeric — entire row should be skipped
        ["S2", "Strabelina ", "B", 2034, sample_date, "NotANumber", *([0.5] * (sensor_count - 1))],
    ]
    bad = _xlsx_bytes(SHEET_NAME, list(EXPECTED_HEADERS), rows)

    report = validate(bad)

    assert report.total_rows == 2
    assert report.valid_rows == 1
    assert len(report.skipped_rows) == 1
    assert report.skipped_rows[0].row_index == 3
    assert "ChlM" in report.skipped_rows[0].reason
