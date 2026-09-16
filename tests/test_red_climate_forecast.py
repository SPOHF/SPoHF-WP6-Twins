"""Tests for the per-height forecast assembly and its presentation rules."""

import pytest

from wp6_data.red.climate.charts import MAX_PROFILES, select_profiles
from wp6_data.red.climate.forecast import (
    ForecastView,
    HeightPoint,
    ProfileSnapshot,
    _combined_uncertainty,
    clamp_physical,
    envelope,
    series_for_height,
)


class TestPhysicalClamping:
    def test_light_never_goes_negative(self):
        """A ridge fit on PAR will predict below zero on a dark hour."""
        assert clamp_physical("par", -1.8) == 0.0

    def test_humidity_is_held_within_its_range(self):
        assert clamp_physical("hum", 104.2) == 100.0
        assert clamp_physical("hum", -3.0) == 0.0

    def test_temperature_has_no_floor_because_cold_is_real(self):
        assert clamp_physical("temp", -4.0) == -4.0

    def test_valid_values_pass_through_untouched(self):
        assert clamp_physical("par", 512.5) == 512.5


class TestCombinedUncertainty:
    def test_links_combine_in_quadrature(self):
        assert _combined_uncertainty(3.0, 4.0) == 5.0

    def test_absent_either_side_yields_none(self):
        """Half an uncertainty would read as a smaller one."""
        assert _combined_uncertainty(None, 4.0) is None
        assert _combined_uncertainty(3.0, None) is None


class TestSelectProfiles:
    def _snapshots(self, horizons):
        return [
            ProfileSnapshot(at=None, horizon_hours=h, points=[]) for h in horizons
        ]

    def test_keeps_the_furthest_horizon(self):
        """Taking the head of the list would drop +24h and +48h — the horizons
        a grower actually plans against."""
        picked = select_profiles(self._snapshots([1, 3, 6, 12, 24, 48]))

        assert picked[-1].horizon_hours == 48
        assert len(picked) == MAX_PROFILES

    def test_spreads_across_the_range_rather_than_clustering(self):
        horizons = [1, 3, 6, 12, 24, 48]

        picked = [s.horizon_hours for s in select_profiles(self._snapshots(horizons))]

        assert picked[0] == horizons[0]      # the nearest is always useful
        assert picked[-1] == horizons[-1]    # so is the furthest
        assert picked == sorted(set(picked))
        # not four horizons that differ by a couple of hours
        assert picked[1] > horizons[0] * 2

    def test_short_lists_pass_through_whole(self):
        picked = select_profiles(self._snapshots([1, 6]))

        assert [s.horizon_hours for s in picked] == [1, 6]


class TestSnapshotVerdicts:
    def test_a_measured_profile_has_no_persistence_verdict(self):
        snapshot = ProfileSnapshot(
            at=None, horizon_hours=0, points=[], measured=True
        )

        assert snapshot.beats_persistence is None

    def test_negative_skill_reads_as_not_beating_persistence(self):
        snapshot = ProfileSnapshot(
            at=None, horizon_hours=24, points=[], skill_vs_persistence=-0.05
        )

        assert snapshot.beats_persistence is False

    def test_view_with_no_points_reports_nothing_to_draw(self):
        view = ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103",
            snapshots=[ProfileSnapshot(at=None, horizon_hours=1, points=[])],
        )

        assert view.has_content is False

    def test_view_separates_predicted_from_measured(self):
        view = ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103",
            snapshots=[
                ProfileSnapshot(
                    at=None, horizon_hours=0, measured=True,
                    points=[HeightPoint(1, "Head", 24.0)],
                ),
                ProfileSnapshot(
                    at=None, horizon_hours=6,
                    points=[HeightPoint(1, "Head", 25.0, uncertainty=1.2)],
                ),
            ],
        )

        assert view.has_content
        assert [s.horizon_hours for s in view.predicted] == [6]


class TestBandHelpers:
    def _view(self, snapshots):
        return ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103", snapshots=snapshots,
        )

    def test_envelope_is_the_coolest_and_warmest_section(self):
        view = self._view([
            ProfileSnapshot(
                at=None, horizon_hours=0, measured=True,
                points=[
                    HeightPoint(1, "Head", 25.9),
                    HeightPoint(3, "Fruit set", 24.5),
                    HeightPoint(5, "Substrate", 24.1),
                ],
            ),
        ])

        assert envelope(view) == [("now", 24.1, 25.9)]

    def test_a_wire_that_lost_a_height_is_not_read_as_a_narrower_crop(self):
        """The band is computed from the sections actually present, so a dead
        sensor shows as a missing section rather than a uniform crop."""
        view = self._view([
            ProfileSnapshot(
                at=None, horizon_hours=6,
                points=[HeightPoint(5, "Substrate", 24.1, uncertainty=1.0)],
            ),
        ])

        assert envelope(view) == [("+6 h", 24.1, 24.1)]
        assert view.heights == [5]

    def test_snapshots_with_no_points_are_skipped_not_zeroed(self):
        view = self._view([ProfileSnapshot(at=None, horizon_hours=1, points=[])])

        assert envelope(view) == []

    def test_series_for_height_carries_uncertainty_and_marks_measured(self):
        view = self._view([
            ProfileSnapshot(
                at=None, horizon_hours=0, measured=True,
                points=[HeightPoint(1, "Head", 25.9)],
            ),
            ProfileSnapshot(
                at=None, horizon_hours=6,
                points=[HeightPoint(1, "Head", 26.8, uncertainty=3.49)],
            ),
        ])

        series = series_for_height(view, 1)

        # the measured point has no uncertainty, which is how the chart knows
        # where to split measured from forecast
        assert series == [("now", 25.9, None), ("+6 h", 26.8, 3.49)]

    def test_an_absent_height_yields_no_points_rather_than_gaps(self):
        view = self._view([
            ProfileSnapshot(
                at=None, horizon_hours=6,
                points=[HeightPoint(5, "Substrate", 24.1)],
            ),
        ])

        assert series_for_height(view, 1) == []

    def test_label_for_falls_back_to_the_height_number(self):
        view = self._view([])

        assert view.label_for(3) == "H3"


class TestHistoryAxis:
    def test_offsets_mirror_the_fitted_horizons(self):
        """Symmetry about 'now' means the eye reads the same distance either
        side of the hinge."""
        from wp6_data.red.climate.forecast import history_offsets

        assert history_offsets([1, 3, 6, 12, 24, 48]) == [-48, -24, -12, -6, -3, -1]

    def test_offsets_follow_the_config_rather_than_a_fixed_list(self):
        from wp6_data.red.climate.forecast import history_offsets

        assert history_offsets([2, 8]) == [-8, -2]

    def test_labels_carry_a_sign_and_now_has_none(self):
        assert ProfileSnapshot(at=None, horizon_hours=0, points=[]).label == "now"
        assert ProfileSnapshot(at=None, horizon_hours=12, points=[]).label == "+12 h"
        assert ProfileSnapshot(at=None, horizon_hours=-12, points=[]).label == "−12 h"

    def test_clock_renders_in_the_display_timezone(self):
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo

        snapshot = ProfileSnapshot(
            at=datetime(2026, 9, 16, 9, 0, tzinfo=UTC), horizon_hours=0, points=[]
        )

        assert snapshot.clock(ZoneInfo("Europe/Amsterdam")) == "Wed 11:00"

    def test_clock_falls_back_to_the_offset_when_undated(self):
        assert ProfileSnapshot(at=None, horizon_hours=6, points=[]).clock(None) == "+6 h"

    def test_only_the_hinge_counts_as_now(self):
        """History is measured too, so the profile chart must not draw seven
        measured profiles on top of each other."""
        past = ProfileSnapshot(at=None, horizon_hours=-24, points=[], measured=True)
        hinge = ProfileSnapshot(at=None, horizon_hours=0, points=[], measured=True)

        assert past.is_now is False
        assert hinge.is_now is True

    def test_view_separates_history_from_the_hinge_and_the_forecast(self):
        view = ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103",
            snapshots=[
                ProfileSnapshot(at=None, horizon_hours=-24, measured=True,
                                points=[HeightPoint(1, "Head", 23.0)]),
                ProfileSnapshot(at=None, horizon_hours=0, measured=True,
                                points=[HeightPoint(1, "Head", 24.0)]),
                ProfileSnapshot(at=None, horizon_hours=6,
                                points=[HeightPoint(1, "Head", 25.0, uncertainty=1.0)]),
            ],
        )

        assert [s.horizon_hours for s in view.history] == [-24]
        assert view.now.horizon_hours == 0
        assert [s.horizon_hours for s in view.predicted] == [6]


class TestOutdoorSeries:
    def test_offset_labels_match_the_snapshot_keys(self):
        """The outdoor line shares the crop's x axis, so its labels must be the
        same strings — a mismatch would silently plot it off the categories."""
        from wp6_data.red.climate.forecast import _offset_label

        for offset in (-48, -1, 0, 1, 48):
            snapshot = ProfileSnapshot(at=None, horizon_hours=offset, points=[])
            assert _offset_label(offset) == snapshot.label

    def test_forecast_half_is_joined_to_the_last_measured_point(self):
        """Otherwise the solid and dashed halves leave a visible gap at 'now'."""
        from wp6_data.red.climate.charts import _outdoor_forecast
        from wp6_data.red.climate.forecast import OutdoorPoint

        view = ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103",
            outdoor=[
                OutdoorPoint("−1 h", 18.4, True),
                OutdoorPoint("now", 18.7, True),
                OutdoorPoint("+1 h", 17.8, False),
            ],
        )

        joined = _outdoor_forecast(view)

        assert [p.label for p in joined] == ["now", "+1 h"]

    def test_no_measured_history_still_yields_a_forecast_half(self):
        from wp6_data.red.climate.charts import _outdoor_forecast
        from wp6_data.red.climate.forecast import OutdoorPoint

        view = ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103",
            outdoor=[OutdoorPoint("+1 h", 17.8, False)],
        )

        assert [p.label for p in _outdoor_forecast(view)] == ["+1 h"]


class TestKnownCaveats:
    """Light is part forecast and part assumption, so the page says which."""

    def _caveat(self, measurement, lamp=None):
        from datetime import UTC, datetime

        from wp6_data.red.climate.forecast import _known_caveats

        return _known_caveats(measurement, datetime(2026, 12, 1, tzinfo=UTC), lamp)

    def _lamp(self, **kwargs):
        from wp6_data.red.lamp import LampModel

        defaults = dict(
            attenuation=0.62, attenuation_days=90, power_par=168.0,
            hours_on=frozenset({22, 23, 0, 1}), observed_days=14,
        )
        return LampModel(**{**defaults, **kwargs})

    def test_light_names_the_lamp_level_and_hours(self):
        caveat = self._caveat("par", self._lamp())[0]

        assert "168" in caveat
        assert "22:00" in caveat

    def test_light_says_the_schedule_is_carried_forward_not_predicted(self):
        """A change to the lamp plan is not something weather can predict."""
        caveat = self._caveat("par", self._lamp())[0]

        assert "carried forward" in caveat
        assert "14 days" in caveat

    def test_unlit_greenhouse_warns_the_forecast_reads_low_if_lamps_start(self):
        caveat = self._caveat("par", self._lamp(power_par=None, hours_on=frozenset()))[0]

        assert "not seen running" in caveat
        assert "read low" in caveat

    def test_a_missing_lamp_model_is_treated_as_unlit_rather_than_silent(self):
        assert self._caveat("par", None)

    def test_measurements_without_a_lamp_dependency_carry_no_caveat(self):
        for measurement in ("temp", "hum", "co2"):
            assert self._caveat(measurement, self._lamp()) == []


class TestBandVisibility:
    """The envelope is subordinate to the section lines, but it still has to be
    visible: at its original 0.10 alpha it sat at 1.16 contrast against the page
    and read as nothing at all."""

    MIN_ALPHA = 0.15

    def _alpha(self, fill: str) -> float:
        return float(fill.rsplit(",", 1)[1].strip(" )"))

    def test_light_band_is_distinguishable_from_the_surface(self):
        from wp6_data.red.climate.charts import BAND_FILL_LIGHT

        assert self._alpha(BAND_FILL_LIGHT) >= self.MIN_ALPHA

    def test_dark_band_is_distinguishable_from_the_surface(self):
        from wp6_data.red.climate.charts import BAND_FILL_DARK

        assert self._alpha(BAND_FILL_DARK) >= self.MIN_ALPHA

    def test_the_band_stays_neutral_not_a_sixth_ramp_step(self):
        """A tinted region would read as another growth section."""
        from wp6_data.red.climate.charts import BAND_FILL_DARK, BAND_FILL_LIGHT

        for fill in (BAND_FILL_LIGHT, BAND_FILL_DARK):
            red, green, blue = (
                int(part) for part in fill[fill.index("(") + 1:].split(",")[:3]
            )
            assert max(red, green, blue) - min(red, green, blue) <= 15


class TestSectionColours:
    """Sections take a single-hue ramp, light at the head to dark at the root.
    Adjacent steps sit under the colour-alone floor by design, so identity rests
    on the direct labels, the stacking order and the table beneath."""

    def test_each_section_gets_its_own_step(self):
        from wp6_data.red.climate.charts import section_colour

        steps = [section_colour(height) for height in range(1, 6)]

        assert len(set(steps)) == 5

    def test_the_ramp_runs_light_at_the_head_to_dark_at_the_root(self):
        from wp6_data.red.climate.charts import SECTION_RAMP_LIGHT, section_colour

        assert section_colour(1) == SECTION_RAMP_LIGHT[0]
        assert section_colour(5) == SECTION_RAMP_LIGHT[-1]

    def test_colour_follows_the_section_not_its_rank(self):
        """A wire that has lost H4 must not repaint H5 with H4's colour."""
        from wp6_data.red.climate.charts import section_colour

        present = [1, 2, 3, 5]  # H4 dead, as on WS_01_01's PAR
        hues = {height: section_colour(height) for height in present}

        assert hues[5] == section_colour(5)
        assert hues[5] != section_colour(4)

    def test_outdoor_is_neutral_so_the_chart_is_one_hue_plus_grey(self):
        """Outdoor is context, not a section, so it does not take a ramp step."""
        from wp6_data.red.climate.charts import (
            OUTDOOR_DARK,
            OUTDOOR_LIGHT,
            SECTION_RAMP_DARK,
            SECTION_RAMP_LIGHT,
        )

        for outdoor, hues in (
            (OUTDOOR_LIGHT, SECTION_RAMP_LIGHT), (OUTDOOR_DARK, SECTION_RAMP_DARK)
        ):
            red, green, blue = (
                int(outdoor[i:i + 2], 16) for i in (1, 3, 5)
            )
            assert max(red, green, blue) - min(red, green, blue) <= 12
            assert outdoor not in hues

    def test_dark_steps_are_selected_not_flipped(self):
        from wp6_data.red.climate.charts import SECTION_RAMP_DARK, SECTION_RAMP_LIGHT

        assert len(SECTION_RAMP_DARK) == len(SECTION_RAMP_LIGHT)
        assert SECTION_RAMP_DARK != SECTION_RAMP_LIGHT
        assert tuple(reversed(SECTION_RAMP_LIGHT)) != SECTION_RAMP_DARK


class TestDirectLabels:
    """Every line is direct-labelled, which is the relief that lets two hues sit
    under 3:1 against the page. A missing label is not cosmetic."""

    def _view(self):
        from datetime import UTC, datetime

        from wp6_data.red.climate.forecast import OutdoorPoint

        def snapshot(horizon, measured, base):
            return ProfileSnapshot(
                at=datetime(2026, 9, 16, 12, tzinfo=UTC),
                horizon_hours=horizon,
                measured=measured,
                points=[
                    HeightPoint(h, f"S{h}", base - h,
                                uncertainty=None if measured else 1.0)
                    for h in range(1, 6)
                ],
            )

        return ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=datetime(2026, 9, 16, 12, tzinfo=UTC),
            reference_key="s2103",
            snapshots=[
                snapshot(-1, True, 26.0), snapshot(0, True, 26.5),
                snapshot(6, False, 27.0), snapshot(24, False, 27.5),
            ],
            outdoor=[
                OutdoorPoint("−1 h", 18.0, True), OutdoorPoint("now", 18.2, True),
                OutdoorPoint("+6 h", 17.5, False), OutdoorPoint("+24 h", 17.0, False),
            ],
        )

    def _html(self):
        from wp6_data.red.climate.charts import forecast_band_chart

        return forecast_band_chart(self._view(), "Europe/Amsterdam")

    def test_every_section_including_h1_is_labelled(self):
        """H1's label was being overwritten by the forecast divider's own
        annotation, because the whole list was assigned rather than appended."""
        html = self._html()

        for height in range(1, 6):
            assert f"H{height} S{height}" in html

    def test_the_forecast_divider_survives_alongside_the_labels(self):
        html = self._html()

        assert "forecast" in html
        assert "H1 S1" in html

    def test_outdoor_is_labelled_too(self):
        assert "Outdoor" in self._html()

    def test_nothing_to_draw_returns_none(self):
        from wp6_data.red.climate.charts import forecast_band_chart

        empty = ForecastView(
            wire="WS_01_02", measurement="temp", unit="°C",
            issued_at=None, reference_key="s2103",
        )

        assert forecast_band_chart(empty, "Europe/Amsterdam") is None


class TestMeasuredResolution:
    """The model trains hourly because that is what it trains on; the chart is
    showing what actually happened, and throws no detail away."""

    def test_history_is_resampled_not_left_raw(self):
        """The relay writes in bursts and received_at is not unique per device,
        so raw points would draw a ragged line with vertical jumps."""
        import pandas as pd

        from wp6_data.red.climate.forecast import HISTORY_RESOLUTION
        from wp6_data.shared.aggregation import resample_to

        burst = pd.to_datetime(["2026-09-16T05:00:01Z"] * 4, utc=True)
        frame = pd.DataFrame({"time": burst, "value": [20.0, 21.0, 22.0, 23.0]})

        dense = resample_to(frame, HISTORY_RESOLUTION)

        assert len(dense) == 1
        assert dense["value"].iloc[0] == pytest.approx(21.5)

    def test_ten_minutes_keeps_six_times_the_detail_of_hourly(self):
        import numpy as np
        import pandas as pd

        from wp6_data.red.climate.forecast import HISTORY_RESOLUTION
        from wp6_data.shared.aggregation import resample_hourly, resample_to

        times = pd.date_range("2026-09-16", periods=288, freq="5min", tz="UTC")
        frame = pd.DataFrame({"time": times, "value": np.arange(288, dtype=float)})

        assert len(resample_to(frame, HISTORY_RESOLUTION)) == 144
        assert len(resample_hourly(frame)) == 24

    def test_gaps_stay_absent_rather_than_zero_filled(self):
        import pandas as pd

        from wp6_data.red.climate.forecast import HISTORY_RESOLUTION
        from wp6_data.shared.aggregation import resample_to

        times = pd.to_datetime(
            ["2026-09-16T00:00Z", "2026-09-16T06:00Z"], utc=True
        )
        frame = pd.DataFrame({"time": times, "value": [20.0, 22.0]})

        dense = resample_to(frame, HISTORY_RESOLUTION)

        assert len(dense) == 2
        assert 0.0 not in dense["value"].tolist()


class TestUncertaintyNote:
    """The spread is a property of the horizon, so it is stated once per horizon
    rather than drawn five times. With a dense horizon set the per-horizon
    figures plateau, and the roll-call stops informing."""

    def _text(self, spreads):
        import re

        from wp6_data.red.routes.climate_forecast import _uncertainty_note

        return re.sub(r"<[^>]+>", "", _uncertainty_note(spreads, "°C"))

    def test_a_short_list_is_stated_in_full(self):
        text = self._text([("+1 h", 1.5), ("+6 h", 3.6)])

        assert "+1 h ± 1.5" in text
        assert "+6 h ± 3.6" in text

    def test_a_dense_list_is_summarised_by_its_range(self):
        from wp6_data.red.routes.climate_forecast import UNCERTAINTY_DETAIL_LIMIT

        spreads = [(f"+{h} h", 1.5 + h * 0.1) for h in range(1, UNCERTAINTY_DETAIL_LIMIT + 3)]

        text = self._text(spreads)

        assert "widening to" in text
        assert text.count("±") == 2  # nearest and widest, not one per horizon

    def test_the_summary_names_the_widest_horizon_not_the_last(self):
        """The spread plateaus, so the last horizon is usually not the worst."""
        spreads = [("+1 h", 1.5), ("+8 h", 3.7), ("+12 h", 3.0), ("+24 h", 2.9),
                   ("+36 h", 3.4), ("+42 h", 3.3), ("+48 h", 3.3)]

        text = self._text(spreads)

        assert "by +8 h" in text

    def test_no_spreads_says_nothing(self):
        assert self._text([]) == ""
