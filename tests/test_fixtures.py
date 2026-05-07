"""Anchor tests for binary fixtures used by parser/CLI/UI slices.

Pinning the fixture path here means a future move or rename breaks the
test loudly, instead of silently breaking downstream parsers when they
fail to find the file.
"""

from pathlib import Path


def test_sijia_seed_fixture_loads_as_nonempty_bytes() -> None:
    fixture = Path(__file__).parent / "fixtures" / "sijia_seed.xlsx"
    data = fixture.read_bytes()
    assert len(data) > 0
