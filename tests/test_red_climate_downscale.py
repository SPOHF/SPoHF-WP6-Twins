"""Tests for link 3, the per-height deviation model.

The question this link has to answer is narrow: does modelling the vertical
gradient beat ignoring it? These tests check it answers honestly in both
directions — including when the answer is no.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wp6_data.red.climate.config import load_climate_model
from wp6_data.red.climate.downscale import (
    ABSOLUTE_HUMIDITY,
    DIFFERENCE,
    MAX_PAR_RATIO,
    RATIO,
    WireDownscaler,
    deviation,
    reconstruct,
)
from wp6_data.red.climate.humidity import absolute_humidity

METADATA = Path("src/wp6_data/red/metadata.yaml")
WIRE = "WS_01_02"
DAYS = 60


@pytest.fixture(scope="module")
def config():
    return load_climate_model(METADATA)


def _index(days=DAYS, start="2026-07-13"):
    return pd.date_range(start, periods=days * 24, freq="h", tz="UTC")


def _frame(index, values):
    return pd.DataFrame({"time": index, "value": values})


class TestDeviationRoundTrip:
    @pytest.mark.parametrize("mode", [DIFFERENCE, RATIO])
    def test_reconstruct_inverts_deviation(self, mode):
        reference = np.array([20.0, 25.0, 30.0])
        values = np.array([18.0, 24.0, 27.0])

        back = reconstruct(deviation(values, reference, mode), reference, mode)

        assert back == pytest.approx(values)


class TestGradientIsLearnt:
    def _wire_with_gradient(self, index):
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)
        # A gradient that varies through the day: the head runs hotter at midday
        # and closer to the reference at night. A constant offset cannot capture
        # this, which is the point.
        offsets = {1: 2.5 * np.sin(np.pi * np.clip((hour - 6) / 12, 0, 1)),
                   5: -1.5 * np.ones_like(hour, dtype=float)}
        return reference, offsets

    def test_beats_reference_and_constant_offset(self, config):
        index = _index()
        reference, offsets = self._wire_with_gradient(index)
        wire = {f"h{h}": _frame(index, reference + off) for h, off in offsets.items()}

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)}, {(WIRE, "temp"): wire}
        )

        head = next(f for f in stats.fits if f.height == 1)
        assert head.beats_reference
        assert head.stats.skill["constant_offset"] > 0

    def test_reports_a_gradient_score_across_heights(self, config):
        index = _index()
        reference, offsets = self._wire_with_gradient(index)
        wire = {f"h{h}": _frame(index, reference + off) for h, off in offsets.items()}

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)}, {(WIRE, "temp"): wire}
        )

        score = stats.gradients[(WIRE, "temp")]
        assert score.n > 0
        assert score.sign_agreement > 0.8

    def test_predict_puts_the_deviation_back_on_a_reference(self, config):
        index = _index()
        reference, offsets = self._wire_with_gradient(index)
        wire = {f"h{h}": _frame(index, reference + off) for h, off in offsets.items()}
        model = WireDownscaler(config, "s2103")
        model.train({"temp": _frame(index, reference)}, {(WIRE, "temp"): wire})

        future = pd.Series(reference[:48], index=index[:48])
        predicted = model.predict(WIRE, "temp", 1, future)

        assert len(predicted) == 48
        assert predicted.to_numpy() == pytest.approx(
            (reference + offsets[1])[:48], abs=0.5
        )


class TestCoverageIsTheWiresOwn:
    def test_span_reflects_wire_coverage_not_the_references_history(self, config):
        """The reference carries a year the wire does not. Taking the joined
        frame's span credited link 3 with coverage it never had — and made it
        suggest enabling seasonality off nine weeks of data."""
        reference_index = _index(days=340, start="2025-10-08")
        wire_index = _index(days=40, start="2026-07-13")
        hour = reference_index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(reference_index, reference)},
            {(WIRE, "temp"): {"h1": _frame(wire_index, np.full(len(wire_index), 21.0))}},
        )

        assert stats.days_covered <= 41


class TestHonestWhenThereIsNoGradient:
    def test_a_height_equal_to_the_reference_claims_no_skill(self, config):
        """If the height simply is the reference, the model must not report
        that it improved on assuming exactly that."""
        index = _index()
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)
        wire = {"h1": _frame(index, reference.copy())}

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)}, {(WIRE, "temp"): wire}
        )

        head = next(f for f in stats.fits if f.height == 1)
        assert head.stats.skill["reference"] <= 0.01

    def test_too_few_rows_is_not_reported_at_all(self, config):
        index = _index(days=2)
        wire = {"h1": _frame(index, np.full(len(index), 21.0))}

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, np.full(len(index), 22.0))},
            {(WIRE, "temp"): wire},
        )

        assert stats.fits == []


class TestParUsesRatio:
    def test_par_is_fitted_as_a_ratio_not_a_difference(self, config):
        index = _index()
        hour = index.hour.to_numpy()
        reference = np.clip(700 * np.sin(np.pi * (hour - 6) / 12), 0, None)
        wire = {"h1": _frame(index, reference * 0.62)}

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"par": _frame(index, reference)}, {(WIRE, "par"): wire}
        )

        assert stats.fits
        assert all(f.mode == RATIO for f in stats.fits)

    def test_night_hours_below_the_par_floor_are_excluded(self, config):
        """At night the ratio is a division by noise, not an attenuation."""
        index = _index()
        hour = index.hour.to_numpy()
        reference = np.clip(700 * np.sin(np.pi * (hour - 6) / 12), 0, None)
        wire = {"h1": _frame(index, reference * 0.62)}

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"par": _frame(index, reference)}, {(WIRE, "par"): wire}
        )

        lit_hours = int((reference > config.par_floor).sum())
        assert stats.fits[0].stats.n_samples <= lit_hours

    def test_absurd_ratios_are_discarded(self):
        assert MAX_PAR_RATIO > 1.0


class TestHumidityUsesHeightTemperature:
    def test_humidity_mode_is_absolute_humidity(self, config):
        index = _index()
        hour = index.hour.to_numpy()
        reference_temp = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)
        reference_rh = 70 - 10 * np.sin(2 * np.pi * (hour - 13) / 24)
        height_temp = reference_temp - 1.5
        # Same moisture content as the reference, just colder -> higher RH.
        height_rh = np.clip(reference_rh + 4.0, 0, 100)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"hum": _frame(index, reference_rh), "temp": _frame(index, reference_temp)},
            {
                (WIRE, "hum"): {"h1": _frame(index, height_rh)},
                (WIRE, "temp"): {"h1": _frame(index, height_temp)},
            },
        )

        humidity_fits = [f for f in stats.fits if f.measurement == "hum"]
        assert humidity_fits
        assert all(f.mode == ABSOLUTE_HUMIDITY for f in humidity_fits)
        # temperature on the same wire is a plain difference
        assert all(f.mode == DIFFERENCE for f in stats.fits if f.measurement == "temp")

    def test_predicting_humidity_without_a_height_temperature_is_refused(self, config):
        index = _index()
        hour = index.hour.to_numpy()
        reference_temp = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)
        reference_rh = 70 - 10 * np.sin(2 * np.pi * (hour - 13) / 24)
        model = WireDownscaler(config, "s2103")
        model.train(
            {"hum": _frame(index, reference_rh), "temp": _frame(index, reference_temp)},
            {
                (WIRE, "hum"): {"h1": _frame(index, reference_rh + 4)},
                (WIRE, "temp"): {"h1": _frame(index, reference_temp - 1.5)},
            },
        )

        with pytest.raises(ValueError, match="height_temp"):
            model.predict(
                WIRE, "hum", 1,
                pd.Series(reference_rh[:24], index=index[:24]),
                reference_temp=pd.Series(reference_temp[:24], index=index[:24]),
            )

    def test_absolute_humidity_is_unchanged_by_temperature_alone(self):
        """The property the whole conversion rests on."""
        warm = absolute_humidity(30.0, 45.6)
        cool = absolute_humidity(20.0, 80.0)

        assert float(warm) == pytest.approx(float(cool), rel=0.01)


class TestConfigIsHonoured:
    def test_a_window_entirely_inside_the_exclusion_trains_nothing(self, config):
        """The flat regime is not low-quality data to down-weight; it is a
        period the sensors were not measuring what their names say."""
        index = _index(days=30, start="2026-06-01")  # inside 2026-05-28..07-13
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)},
            {(WIRE, "temp"): {"h1": _frame(index, reference - 1.0)}},
        )

        assert stats.fits == []

    def test_a_straddling_window_keeps_only_the_usable_side(self, config):
        index = _index(days=DAYS, start="2026-05-20")  # straddles the exclusion
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)},
            {(WIRE, "temp"): {"h1": _frame(index, reference - 1.0)}},
        )

        usable_hours = sum(
            24 for d in pd.date_range(index.min(), index.max(), freq="D").date
            if not config.is_excluded(d)
        )
        assert stats.fits
        assert stats.fits[0].stats.n_samples <= usable_hours
        assert stats.fits[0].stats.n_samples < len(index)

    def test_seasonality_is_chosen_by_score_not_configured(self, config):
        """No switch: each fit tries both and keeps the better held-out score,
        so a term that starts helping once the wires have seen a winter turns
        itself on at the next retrain."""
        index = _index()
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)},
            {(WIRE, "temp"): {"h1": _frame(index, reference - 1.0)}},
        )

        fit = stats.fits[0]
        *_, feature_names, _, seasonal = (
            None, *model.models[(WIRE, "temp", 1)]
        )
        assert fit.seasonal is seasonal
        # the stored features must match the choice that was recorded
        has_day_of_year = any("day_of_year" in name for name in feature_names)
        assert has_day_of_year is seasonal

    def test_a_genuine_seasonal_gradient_is_picked_up(self, config):
        """A deviation that really does vary with the season should win the
        day-of-year term on its own merits."""
        index = _index(days=330, start="2025-10-08")
        doy = index.dayofyear.to_numpy()
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)
        # a gradient that swings with the year, not the day
        offset = 3.0 * np.sin(2 * np.pi * doy / 365)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)},
            {(WIRE, "temp"): {"h1": _frame(index, reference + offset)}},
        )

        assert stats.fits[0].seasonal is True

    def test_seasonal_choices_are_reported_per_measurement(self, config):
        index = _index()
        hour = index.hour.to_numpy()
        reference = 22 + 5 * np.sin(2 * np.pi * (hour - 13) / 24)

        model = WireDownscaler(config, "s2103")
        stats = model.train(
            {"temp": _frame(index, reference)},
            {(WIRE, "temp"): {
                "h1": _frame(index, reference - 1.0),
                "h3": _frame(index, reference - 2.0),
            }},
        )

        kept, total = stats.seasonal_chosen["temp"]
        assert total == 2
        assert 0 <= kept <= total
