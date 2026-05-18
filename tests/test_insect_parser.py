"""Tests for the blue insect-trap CSV parser.

A pure deep module over bytes (no DB), so it gets the densest coverage:
exact-header structural fast-fail; per-row skipped-row reasons; tz-naive →
Europe/Amsterdam → UTC across a DST boundary; mean-bucketing of exact-
duplicate timestamps; empty-`suzukii` cells skipped; and the
ValidationReport facts. Source constants are used rather than magic numbers
so the tests survive behaviour-preserving refactors.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from wp6_data.blue.insects.parser import (
    DEVICE_KEY,
    EXPECTED_HEADER,
    LOCAL_TZ,
    SOURCE,
    InsectParseError,
    parse,
    validate,
)

SEED_PATH = Path(__file__).parent / "fixtures" / "insect_seed.csv"


@pytest.fixture(scope="module")
def seed_bytes() -> bytes:
    return SEED_PATH.read_bytes()


def _csv_bytes(lines: list[str], *, newline: str = "\n") -> bytes:
    return newline.join(lines).encode("utf-8")


def _header() -> str:
    return ",".join(EXPECTED_HEADER)


# --- structural fast-fail ------------------------------------------------

def test_wrong_header_raises_parse_error():
    bad = _csv_bytes(["time,total,sw", "2024-07-15 09:00:00,10,"])
    with pytest.raises(InsectParseError):
        parse(bad)


def test_empty_file_raises_parse_error():
    with pytest.raises(InsectParseError):
        parse(b"")


def test_reordered_columns_raise_parse_error():
    bad = _csv_bytes([
        "timestamp,suzukii,total_insects",
        "2024-07-15 09:00:00,,10",
    ])
    with pytest.raises(InsectParseError):
        parse(bad)


# --- per-row skipped reasons --------------------------------------------

def test_non_numeric_value_is_skipped_with_reason():
    csv = _csv_bytes([_header(), "2024-07-15 09:00:00,abc,"])
    report = validate(csv)
    assert report.total_rows == 1
    assert report.valid_rows == 0
    assert len(report.skipped_rows) == 1
    skipped = report.skipped_rows[0]
    assert skipped.row_index == 2  # header is line 1
    assert "total_insects" in skipped.reason


def test_bad_timestamp_is_skipped_with_reason():
    csv = _csv_bytes([_header(), "not-a-date,10,"])
    report = validate(csv)
    assert len(report.skipped_rows) == 1
    assert "timestamp" in report.skipped_rows[0].reason


def test_wrong_column_count_is_skipped_with_reason():
    csv = _csv_bytes([_header(), "2024-07-15 09:00:00,10"])
    report = validate(csv)
    assert len(report.skipped_rows) == 1
    assert "column" in report.skipped_rows[0].reason


# --- timezone conversion (DST-aware) ------------------------------------

def test_summer_timestamp_converted_from_cest_to_utc():
    """July is CEST (UTC+2): 09:00 local → 07:00 UTC."""
    csv = _csv_bytes([_header(), "2024-07-15 09:00:00,20,"])
    (reading,) = parse(csv)
    assert reading.time == datetime(2024, 7, 15, 7, 0, tzinfo=UTC)


def test_winter_timestamp_converted_from_cet_to_utc():
    """January is CET (UTC+1): 09:00 local → 08:00 UTC — proves the
    conversion is DST-aware, not a fixed offset."""
    csv = _csv_bytes([_header(), "2024-01-15 09:00:00,10,"])
    (reading,) = parse(csv)
    assert reading.time == datetime(2024, 1, 15, 8, 0, tzinfo=UTC)


def test_local_then_utc_round_trip_matches_zoneinfo():
    csv = _csv_bytes([_header(), "2024-07-15 09:00:00,20,"])
    (reading,) = parse(csv)
    expected = datetime(2024, 7, 15, 9, 0, tzinfo=LOCAL_TZ).astimezone(UTC)
    assert reading.time == expected


# --- mean-bucketing of exact-duplicate timestamps -----------------------

def test_duplicate_timestamp_rows_are_mean_bucketed():
    csv = _csv_bytes([
        _header(),
        "2024-07-15 10:00:00,30,",
        "2024-07-15 10:00:00,50,",
    ])
    readings = parse(csv)
    assert len(readings) == 1  # one (device, sensor, time) tuple
    assert readings[0].value == 40.0  # mean(30, 50), not sum


# --- empty suzukii cells -------------------------------------------------

def test_empty_suzukii_cells_emit_no_reading():
    csv = _csv_bytes([
        _header(),
        "2024-07-15 09:00:00,20,",
        "2024-07-16 09:00:00,25,",
    ])
    readings = parse(csv)
    assert {r.sensor_tag for r in readings} == {"total_insects"}


def test_populated_suzukii_cell_emits_reading():
    csv = _csv_bytes([_header(), "2024-07-16 09:00:00,40,5"])
    readings = parse(csv)
    by_sensor = {r.sensor_tag: r.value for r in readings}
    assert by_sensor == {"total_insects": 40.0, "suzukii": 5.0}


# --- ValidationReport facts (against the committed fixture) -------------

def test_seed_validation_report_facts(seed_bytes: bytes):
    report = validate(seed_bytes)

    assert report.total_rows == 7
    assert report.valid_rows == 5  # 2 skipped: bad number + bad timestamp
    assert len(report.skipped_rows) == 2
    # total_insects: Jan(10), Jul 07:00(20), Jul 08:00 mean(30,50), Jul-16(40)
    # + one suzukii(5) → 5 emitted rows after bucketing
    assert report.emitted_row_count == 5
    assert report.devices == (DEVICE_KEY,)
    assert report.sensors == ("suzukii", "total_insects")
    assert report.date_range == (date(2024, 1, 15), date(2024, 7, 16))


def test_seed_readings_are_tagged_with_source_and_single_device(
    seed_bytes: bytes,
):
    readings = parse(seed_bytes)
    assert {r.source for r in readings} == {SOURCE}
    assert {r.device_name for r in readings} == {DEVICE_KEY}


# --- CRLF tolerance ------------------------------------------------------

def test_crlf_line_endings_are_tolerated():
    csv = _csv_bytes(
        [_header(), "2024-07-15 09:00:00,20,"], newline="\r\n",
    )
    (reading,) = parse(csv)
    assert reading.time == datetime(2024, 7, 15, 7, 0, tzinfo=UTC)
