"""Tests for blue's season config loader.

Blue declares seasons but no cohort rhythm — that absence is the whole
difference from red, so the tests assert the shape rather than assuming it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wp6_data.blue.seasons.config import load_seasons

BLUE_METADATA = Path(__file__).parent.parent / "src/wp6_data/blue/metadata.yaml"

MINIMAL = """
seasons:
  weather:
    metrics:
      - key: temp
        label: Temp
        unit: "C"
        device: weatherstation
        sensor: airTemperature
        agg: avg
  seasons:
    - label: "one"
      start: 2025-03-01
      end: 2025-11-01
"""


class TestLoadSeasons:
    def test_loads_the_real_blue_block(self):
        config = load_seasons(BLUE_METADATA)
        assert config.seasons
        assert config.weather.metrics

    def test_seasons_do_not_overlap(self):
        """Attachment picks the first containing season, so overlap would hide one."""
        seasons = sorted(load_seasons(BLUE_METADATA).seasons, key=lambda s: s.start)
        for earlier, later in zip(seasons, seasons[1:], strict=False):
            assert earlier.end <= later.start

    def test_every_season_ends_after_it_starts(self):
        for season in load_seasons(BLUE_METADATA).seasons:
            assert season.end > season.start

    def test_missing_block_raises(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text("devices: {}\n")
        with pytest.raises(ValueError, match="no 'seasons' block"):
            load_seasons(p)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no metadata file"):
            load_seasons(tmp_path / "nope.yaml")

    def test_omitted_field_raises_rather_than_defaulting(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(MINIMAL.replace("        unit: \"C\"\n", ""))
        with pytest.raises(ValueError):
            load_seasons(p)

    def test_unsupported_agg_raises(self, tmp_path):
        p = tmp_path / "m.yaml"
        p.write_text(MINIMAL.replace("agg: avg", "agg: median"))
        with pytest.raises(ValueError, match="unknown agg"):
            load_seasons(p)


class TestMetricSelection:
    def test_unknown_metric_key_falls_back_to_the_first(self):
        config = load_seasons(BLUE_METADATA)
        assert config.metric("nope") == config.weather.metrics[0]

    def test_named_metric_wins(self):
        config = load_seasons(BLUE_METADATA)
        wanted = config.weather.metrics[-1]
        assert config.metric(wanted.key).key == wanted.key
