"""Unit tests for the blue fertigation-events CSV parser."""

from datetime import UTC, date, datetime

import pytest

from wp6_data.blue.fertigation_events import (
    EXPECTED_HEADER,
    SOURCE,
    FertigationEventsParseError,
    parse,
    validate,
)


def _csv_bytes(lines: list[str], *, newline: str = "\n") -> bytes:
    return newline.join(lines).encode("utf-8")


def _header() -> str:
    return ",".join(EXPECTED_HEADER)


def test_wrong_header_raises_parse_error() -> None:
    bad = _csv_bytes(["date,treatment_code,volume_ml_per_plant", "2025-04-29,Ca,1333.2"])
    with pytest.raises(FertigationEventsParseError):
        parse(bad)


def test_empty_file_raises_parse_error() -> None:
    with pytest.raises(FertigationEventsParseError):
        parse(b"")


def test_emits_expected_numeric_sensors_per_row() -> None:
    csv = _csv_bytes([
        _header(),
        "2025-04-29,6,Ca,Ca,1333.2,10.0,",
    ])
    readings = parse(csv)

    assert {r.source for r in readings} == {SOURCE}
    assert {r.device_name for r in readings} == {"Ca"}
    assert {r.sensor_tag for r in readings} == {
        "program_id",
        "volume_ml_per_plant",
        "duration_min",
    }
    assert {r.time for r in readings} == {datetime(2025, 4, 29, 0, 0, 1, tzinfo=UTC)}


def test_missing_treatment_code_falls_back_to_treatment_name() -> None:
    csv = _csv_bytes([
        _header(),
        "2025-04-29,6,,V_Ca,1333.2,10.0,",
    ])
    readings = parse(csv)
    assert {r.device_name for r in readings} == {"V_Ca"}


def test_non_numeric_value_is_skipped_with_reason() -> None:
    csv = _csv_bytes([
        _header(),
        "2025-04-29,6,Ca,Ca,nope,10.0,",
    ])
    report = validate(csv)
    assert report.total_rows == 1
    assert report.valid_rows == 0
    assert report.emitted_row_count == 0
    assert len(report.skipped_rows) == 1
    assert "volume_ml_per_plant" in report.skipped_rows[0].reason


def test_bad_date_is_skipped_with_reason() -> None:
    csv = _csv_bytes([
        _header(),
        "2025/04/29,6,Ca,Ca,1333.2,10.0,",
    ])
    report = validate(csv)
    assert len(report.skipped_rows) == 1
    assert "YYYY-MM-DD" in report.skipped_rows[0].reason


def test_validation_report_facts() -> None:
    csv = _csv_bytes([
        _header(),
        "2025-04-29,6,Ca,Ca,1333.2,10.0,",
        "2025-05-09,6,Std,Standaard,1333.2,10.0,",
    ])
    report = validate(csv)
    assert report.total_rows == 2
    assert report.valid_rows == 2
    assert report.emitted_row_count == 6
    assert set(report.devices) == {"Ca", "Std"}
    assert set(report.sensors) == {
        "program_id",
        "volume_ml_per_plant",
        "duration_min",
    }
    assert report.date_range == (date(2025, 4, 29), date(2025, 5, 9))


def test_crlf_line_endings_are_tolerated() -> None:
    csv = _csv_bytes(
        [_header(), "2025-04-29,6,Ca,Ca,1333.2,10.0,"],
        newline="\r\n",
    )
    readings = parse(csv)
    assert len(readings) == 3
