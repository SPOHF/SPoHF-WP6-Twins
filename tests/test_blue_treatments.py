"""Consistency of the blue treatment vocabulary in blue/treatments.py."""

from wp6_data.blue.treatments import (
    FERTILIZER_XLSX_TREATMENT_MAP,
    LONG_DATA_TREATMENT_MAP,
    TREATMENT_COLORS,
    TREATMENT_ORDER,
    treatment_color,
)


def test_long_data_aliases_map_to_canonical_treatments():
    assert set(LONG_DATA_TREATMENT_MAP.values()) == set(TREATMENT_ORDER)


def test_fertilizer_xlsx_aliases_map_to_canonical_treatments():
    assert set(FERTILIZER_XLSX_TREATMENT_MAP.values()) <= set(TREATMENT_ORDER)


def test_every_canonical_treatment_has_a_colour():
    for treatment in TREATMENT_ORDER:
        assert treatment in TREATMENT_COLORS


def test_unknown_treatment_gets_fallback_colour():
    assert treatment_color("no-such-treatment").startswith("#")
