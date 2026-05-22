"""Unit tests for the blue ``long_data`` decoder (no database).

Builds synthetic .xlsx bytes in memory so the tests pin the decoder's external
behaviour — vocabulary harmonization, device modelling, sample-ordinal
timestamps — without committing binary fixtures.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import Workbook

from wp6_data.blue.long_data import (
    SOURCE,
    LongDataParseError,
    _calendar_year_scope,
    parse,
    validate,
)

# Header shapes for the two layouts (2024 has no Plant_nr).
H_2024 = ("Date", "Meting", "Treatment", "Value")
H_2025 = ("Date", "Meting", "Plant_nr", "Treatment", "Value")


def _xlsx(header: tuple, rows: list[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _by_device(readings: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in readings:
        out.setdefault(r.device_name, []).append(r)
    return out


def test_2025_layout_maps_to_per_plant_device() -> None:
    data = _xlsx(H_2025, [(date(2025, 7, 31), "Shoot_Length", 12, "Organisch-1", 90.0)])
    (r,) = parse(data)
    assert r.source == SOURCE
    assert r.device_name == "Org1 / plant 12"
    assert r.sensor_tag == "shoot_length"
    assert r.value == 90.0


def test_2024_layout_has_no_plant_so_treatment_level_device() -> None:
    data = _xlsx(H_2024, [(date(2024, 8, 16), "Shoot_Length", "Standard", 77.0)])
    (r,) = parse(data)
    assert r.device_name == "Std / plant 0"
    assert r.sensor_tag == "shoot_length"


@pytest.mark.parametrize(
    ("treatment", "code"),
    [
        ("Calcium", "Ca"), ("Ca", "Ca"),
        ("Kalium", "K"), ("K", "K"),
        ("Organisch-2", "Org2"), ("Organic 2", "Org2"),
        ("Standaard", "Std"),
        ("V_K_G_CaBrP", "V_K_G_CaBrP"),  # 2025 regime passes through
        ("G_K", "G_K"),
    ],
)
def test_treatment_harmonization(treatment: str, code: str) -> None:
    data = _xlsx(H_2025, [(date(2025, 6, 12), "Score", 1, treatment, 7.0)])
    (r,) = parse(data)
    assert r.device_name == f"{code} / plant 1"


@pytest.mark.parametrize(
    ("meting", "sensor_tag"),
    [
        ("Brix Sugar content (pre storage)", "brix"),
        ("Brix", "brix"),
        ("Brix Sugar content (after storage)", "brix_after_storage"),
        ("Firmness", "firmness"),
        ("Firmness (after storing)", "firmness_after_storage"),
        ("Weight per Berry before storing", "berry_weight"),
        ("Weigth per berry", "berry_weight"),
        ("Oogst gewicht per plant", "yield_per_plant"),
        ("Yield per plant", "yield_per_plant"),
        ("Flowering score", "flowering_score"),
    ],
)
def test_measure_harmonization(meting: str, sensor_tag: str) -> None:
    data = _xlsx(H_2025, [(date(2025, 7, 31), meting, 3, "Standaard", 5.0)])
    (r,) = parse(data)
    assert r.sensor_tag == sensor_tag


def test_pooled_sample_goes_to_plant0_even_with_plant_nr() -> None:
    """Storage-sample measures are per-treatment, so they ignore Plant_nr."""
    data = _xlsx(H_2025, [(date(2025, 9, 3), "Weigth before storage", 16, "Ca", 580.0)])
    (r,) = parse(data)
    assert r.sensor_tag == "sample_weight_before_storage"
    assert r.device_name == "Ca / plant 0"


def test_samples_get_ordinal_timestamps_preserving_order() -> None:
    """N samples in one (device, date, measure) group → N rows at +1s, +2s, …
    (00:00:00 reserved), in file order, none averaged."""
    day = date(2024, 10, 2)
    rows = [(day, "Shoot_Length", "Standard", v) for v in (85.0, 80.0, 90.0)]
    readings = parse(_xlsx(H_2024, rows))
    assert len(readings) == 3
    midnight = datetime(2024, 10, 2, tzinfo=UTC)
    assert [r.time for r in readings] == [
        midnight + timedelta(seconds=1),
        midnight + timedelta(seconds=2),
        midnight + timedelta(seconds=3),
    ]
    assert [r.value for r in readings] == [85.0, 80.0, 90.0]  # order preserved
    assert midnight not in {r.time for r in readings}  # midnight reserved


def test_distinct_plants_do_not_share_ordinals() -> None:
    rows = [
        (date(2025, 7, 31), "Shoot_Length", 1, "Standaard", 50.0),
        (date(2025, 7, 31), "Shoot_Length", 2, "Standaard", 60.0),
    ]
    by_dev = _by_device(parse(_xlsx(H_2025, rows)))
    assert set(by_dev) == {"Std / plant 1", "Std / plant 2"}
    # each is the first (and only) sample in its own group → +1s
    for readings in by_dev.values():
        assert readings[0].time == datetime(2025, 7, 31, tzinfo=UTC) + timedelta(seconds=1)


def test_ignored_measures_are_dropped_not_skipped() -> None:
    data = _xlsx(H_2025, [
        (date(2025, 9, 3), "Total Yield per plant", 1, "Standaard", 1500.0),
        (date(2025, 9, 3), "Shoot_Length", 1, "Standaard", 80.0),
    ])
    report = validate(data)
    assert report.emitted_row_count == 1  # only shoot_length stored
    assert report.skipped_rows == ()  # the cumulative row is not an error
    assert report.total_rows == 1


def test_unknown_measure_becomes_skipped_row() -> None:
    data = _xlsx(H_2025, [(date(2025, 9, 3), "Mystery Metric", 1, "Standaard", 1.0)])
    report = validate(data)
    assert report.emitted_row_count == 0
    assert len(report.skipped_rows) == 1
    assert "Mystery Metric" in report.skipped_rows[0].reason


def test_unknown_treatment_becomes_skipped_row() -> None:
    data = _xlsx(H_2025, [(date(2025, 9, 3), "Score", 1, "Phosphor", 7.0)])
    report = validate(data)
    assert len(report.skipped_rows) == 1
    assert "Phosphor" in report.skipped_rows[0].reason


def test_non_numeric_value_becomes_skipped_row() -> None:
    data = _xlsx(H_2025, [(date(2025, 9, 3), "Score", 1, "Standaard", "n/a")])
    report = validate(data)
    assert report.emitted_row_count == 0
    assert len(report.skipped_rows) == 1


def test_blank_value_is_dropped_not_skipped() -> None:
    """An empty Value cell is absence (no reading), not an error to fix."""
    data = _xlsx(H_2025, [
        (date(2025, 9, 3), "Shoot_Length", 1, "Standaard", None),
        (date(2025, 9, 3), "Shoot_Length", 2, "Standaard", 80.0),
    ])
    report = validate(data)
    assert report.emitted_row_count == 1
    assert report.skipped_rows == ()
    assert report.total_rows == 1


def test_missing_required_column_fast_fails() -> None:
    bad = _xlsx(("Date", "Meting", "Treatment"), [])  # no Value column
    with pytest.raises(LongDataParseError):
        parse(bad)


def test_validation_report_facts() -> None:
    data = _xlsx(H_2025, [
        (date(2025, 6, 12), "Shoot_Length", 1, "Standaard", 50.0),
        (date(2025, 7, 31), "Brix", 1, "Standaard", 12.0),
        (date(2025, 9, 3), "Score", 2, "Ca", 8.0),
    ])
    report = validate(data)
    assert report.total_rows == 3
    assert report.valid_rows == 3
    assert report.emitted_row_count == 3  # one reading per kept row
    assert set(report.sensors) == {"shoot_length", "brix", "score"}
    assert set(report.devices) == {"Std / plant 1", "Ca / plant 2"}
    assert report.date_range == (date(2025, 6, 12), date(2025, 9, 3))


def test_calendar_year_scope_bounds_the_year() -> None:
    clause, params = _calendar_year_scope((date(2025, 4, 3), date(2025, 9, 3)))
    assert params == [date(2025, 1, 1), date(2026, 1, 1)]
    assert "time >=" in clause and "time <" in clause
