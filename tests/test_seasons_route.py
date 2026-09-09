"""End-to-end-ish test of blue's seasons page against a stub provider.

Exercises the whole route — config, lane building, summarising, chart and the
honesty notes — without a database, so the page's contract is covered where
neither the datalake nor TSDB is reachable.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pandas as pd
import pytest

from wp6_data.blue import deps
from wp6_data.blue.routes.seasons import seasons_page
from wp6_data.blue.seasons.config import load_seasons
from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.templates.config import configure_dashboard

CONFIG = load_seasons(deps.METADATA_PATH)
SEASONS = sorted(CONFIG.seasons, key=lambda s: s.start)
TREATMENTS = [
    d for d, m in deps.metadata.devices.items() if m.source == "long_data"
]


@pytest.fixture(autouse=True)
def _dashboard_configured():
    """render_page needs a configured twin; the app does this at startup."""
    configure_dashboard("blue", title="Blue test")


class StubProvider:
    """Daily weather for bucketed reads, treatment measurements otherwise."""

    def __init__(self, *, measured_seasons=(), stray_days=(), weather_days=None):
        self.measured_seasons = measured_seasons
        self.stray_days = stray_days
        self.weather_days = weather_days

    async def fetch_data(self, sensor_tags=None, device_names=None, start=None,
                         end=None, limit=500_000, *, bucket=None, agg=None):
        if bucket is not None and agg not in CHART_AGG_FUNCS:
            raise ValueError(f"Unknown aggregation {agg!r}")
        if bucket is not None:                        # the weather leg
            first, last = SEASONS[0].start, SEASONS[-1].end
            days = self.weather_days
            if days is None:
                days = (last - first).days
            return pd.DataFrame({
                "device": ["weatherstation"] * days,
                "sensor": ["airTemperature"] * days,
                "time": pd.date_range(
                    pd.Timestamp(first, tz="UTC"), periods=days, freq="D"
                ),
                "value": [18.0] * days,
            })

        rows = []                                     # the measurement leg
        for season in self.measured_seasons:
            midpoint = season.start + (season.end - season.start) / 2
            for i, device in enumerate(device_names or TREATMENTS):
                rows.append({
                    "device": device, "sensor": "brix",
                    "time": pd.Timestamp(midpoint, tz="UTC"),
                    "value": 10.0 + i,
                })
        for day in self.stray_days:
            rows.append({
                "device": (device_names or TREATMENTS)[0], "sensor": "brix",
                "time": pd.Timestamp(day, tz="UTC"), "value": 9.9,
            })
        return pd.DataFrame(rows, columns=["device", "sensor", "time", "value"])


def _page(**kwargs) -> str:
    provider = kwargs.pop("provider")
    return asyncio.run(seasons_page(provider=provider, **kwargs))


class TestSeasonsPage:
    def test_renders_a_lane_for_every_treatment_in_every_season(self):
        html = _page(provider=StubProvider())
        for treatment in TREATMENTS:
            assert treatment in html
        for season in SEASONS:
            assert season.label in html

    def test_both_selectors_are_present(self):
        html = _page(provider=StubProvider())
        for label in ("Weather:", "Measure:"):
            assert label in html

    def test_there_is_no_season_selector(self):
        """Seasons are consecutive years, not alternatives — nothing to pick."""
        html = _page(provider=StubProvider())
        assert "Season:" not in html
        assert "season=" not in html

    def test_measured_count_is_reported(self):
        html = _page(provider=StubProvider(measured_seasons=SEASONS[:1]))
        assert f"{len(TREATMENTS)} of {len(TREATMENTS) * len(SEASONS)}" in html

    def test_unattached_measurement_raises_a_visible_warning(self):
        stray = SEASONS[0].start - timedelta(days=10)
        html = _page(provider=StubProvider(stray_days=[stray]))
        assert "fell outside every declared season" in html
        assert "season dates are likely wrong" in html

    def test_no_warning_when_everything_attaches(self):
        html = _page(provider=StubProvider(measured_seasons=SEASONS[:1]))
        assert "fell outside every declared season" not in html

    def test_partial_weather_coverage_is_called_out(self):
        html = _page(provider=StubProvider(weather_days=20))
        assert "show gaps" in html

    def test_full_weather_coverage_is_not_called_out(self):
        html = _page(provider=StubProvider())
        assert "show gaps" not in html

    def test_unknown_selectors_fall_back_rather_than_failing(self):
        html = _page(provider=StubProvider(), measure="nope", weather="nope")
        assert "Weather:" in html
