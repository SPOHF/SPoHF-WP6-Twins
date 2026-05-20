"""Tests for application settings."""

import os
from unittest.mock import patch

from wp6_data.config import RedSettings


def test_red_settings_reads_tsdb_url_from_env():
    """RedSettings.tsdb_url is parsed from WP6_RED_TSDB_URL env var."""
    expected = "postgresql://wp6_red:pw@wp6-data-timescaledb:5432/wp6_red"
    with patch.dict(os.environ, {"WP6_RED_TSDB_URL": expected}, clear=False):
        settings = RedSettings(_env_file=None)
    assert settings.tsdb_url == expected
