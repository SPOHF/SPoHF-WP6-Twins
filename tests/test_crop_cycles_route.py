"""End-to-end-ish test of the red crop-cycles page against a stub provider.

Exercises the whole route — config, cohort generation, attachment, chart and the
honesty notes — without a database, so the page's contract is covered even where
neither MySQL nor TSDB is reachable.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pandas as pd
import pytest

from wp6_data.red import deps
from wp6_data.red.crop_cycles.config import load_crop_cycles, to_cohort_spec, to_cycle_spec
from wp6_data.red.routes.crop_cycles import crop_cycles_page
from wp6_data.shared.aggregation import CHART_AGG_FUNCS
from wp6_data.shared.cycles import generate_cohorts
from wp6_data.shared.templates.config import configure_dashboard

CONFIG = load_crop_cycles(deps._METADATA_PATH)
SPEC = to_cohort_spec(CONFIG)
# The page draws every declared cycle at once, so the fixtures span all of them.
CYCLES = sorted(CONFIG.cycles, key=lambda c: c.start)
COHORTS = [
    cohort
    for cycle in CYCLES
    for cohort in generate_cohorts(to_cycle_spec(cycle), SPEC)
]
FIRST = min(c.start for c in CYCLES)
LAST = max(c.end for c in CYCLES)
SIJIA_DEVICES = [
    d for d, m in deps.metadata.devices.items() if m.source == "sijia"
]


@pytest.fixture(autouse=True)
def _dashboard_configured():
    """render_page needs a configured twin; the app does this at startup."""
    configure_dashboard("red", title="Red test")


class StubProvider:
    """Returns daily climate for bucketed reads and measurements otherwise."""

    def __init__(self, *, measured_cohorts=(), stray_days=(), climate_days=None):
        self.measured_cohorts = measured_cohorts
        self.stray_days = stray_days
        self.climate_days = climate_days

    async def fetch_data(self, sensor_tags=None, device_names=None, start=None,
                         end=None, limit=500_000, *, bucket=None, agg=None):
        # Mirror the real provider's contract: a bucketed read must name a
        # platform aggregation. Accepting anything here is what let an invalid
        # `agg` reach a running server.
        if bucket is not None and agg not in CHART_AGG_FUNCS:
            raise ValueError(
                f"Unknown aggregation {agg!r}; expected one of "
                f"{sorted(CHART_AGG_FUNCS)}"
            )
        if bucket is not None:                       # the climate leg
            days = self.climate_days
            if days is None:
                days = (LAST - FIRST).days
            return pd.DataFrame({
                "device": ["climate"] * days,
                "sensor": ["temp"] * days,
                "time": pd.date_range(
                    pd.Timestamp(FIRST, tz="UTC"), periods=days, freq="D"
                ),
                "value": [20.0] * days,
            })

        rows = []                                     # the measurement leg
        for cohort in self.measured_cohorts:
            for i, device in enumerate(device_names or SIJIA_DEVICES):
                rows.append({
                    "device": device, "sensor": "brix",
                    "time": pd.Timestamp(cohort.end, tz="UTC"),
                    "value": 3.5 + i,
                })
        for day in self.stray_days:
            rows.append({
                "device": (device_names or SIJIA_DEVICES)[0], "sensor": "brix",
                "time": pd.Timestamp(day, tz="UTC"), "value": 9.9,
            })
        return pd.DataFrame(
            rows, columns=["device", "sensor", "time", "value"]
        )


def _page(**kwargs) -> str:
    provider = kwargs.pop("provider")
    return asyncio.run(crop_cycles_page(provider=provider, **kwargs))


class TestCropCyclesPage:
    def test_renders_a_lane_for_every_cohort(self):
        html = _page(provider=StubProvider())
        for cohort in COHORTS:
            assert cohort.label.split(" · ")[0] in html

    def test_the_three_selectors_are_present(self):
        html = _page(provider=StubProvider())
        for label in ("Climate:", "Measure:", "Cultivar:"):
            assert label in html

    def test_there_is_no_cycle_selector(self):
        """Cycles are consecutive seasons, not alternatives — nothing to pick."""
        html = _page(provider=StubProvider())
        assert "Crop cycle:" not in html
        assert "cycle=" not in html

    def test_every_cycle_is_drawn_and_labelled_as_a_group(self):
        html = _page(provider=StubProvider())
        for cycle in CYCLES:
            assert cycle.label in html

    def test_measured_count_is_reported(self):
        html = _page(provider=StubProvider(measured_cohorts=COHORTS[:3]))
        assert f"3 of {len(COHORTS)} cohorts carry" in html

    def test_unattached_measurement_raises_a_visible_warning(self):
        html = _page(provider=StubProvider(stray_days=[FIRST]))
        assert "fell outside every cohort" in html
        assert "cycle dates are likely wrong" in html

    def test_no_warning_when_everything_attaches(self):
        html = _page(provider=StubProvider(measured_cohorts=COHORTS[:2]))
        assert "fell outside every cohort" not in html

    def test_partial_climate_coverage_is_called_out(self):
        html = _page(provider=StubProvider(climate_days=20))
        assert "only partly covered" in html

    def test_full_climate_coverage_is_not_called_out(self):
        html = _page(provider=StubProvider())
        assert "only partly covered" not in html

    def test_unknown_selectors_fall_back_rather_than_failing(self):
        html = _page(
            provider=StubProvider(), measure="nope", climate="nope", variety="nope"
        )
        assert "Climate:" in html

    def test_single_cultivar_can_be_selected(self):
        html = _page(
            provider=StubProvider(measured_cohorts=COHORTS[:2]),
            variety=SIJIA_DEVICES[0],
        )
        assert "Cultivar:" in html


class TestSpecInvariants:
    def test_the_configured_model_keeps_several_cohorts_in_flight(self):
        assert SPEC.overlap == SPEC.duration // SPEC.interval
        assert SPEC.overlap > 1, "a non-overlapping model needs no waterfall"

    def test_cohorts_step_by_the_configured_interval(self):
        assert COHORTS[1].start - COHORTS[0].start == timedelta(
            days=CONFIG.cohort.interval_days
        )

    def test_cohorts_from_every_cycle_are_generated(self):
        assert {c.cycle_label for c in COHORTS} == {c.label for c in CYCLES}
