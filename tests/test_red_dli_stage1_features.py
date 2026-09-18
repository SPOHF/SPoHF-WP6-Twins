"""Stage 1 carries no seasonal feature, and serving supplies what it was fitted on.

Stage 1 maps a modelled sky onto a lux sensor standing in the open. Its
radiation input already *is* the season, so a calendar feature beside it gives
ridge two collinear ways to say "it is June"; weight spreads across both and the
radiation coefficient is left too small to tell a bright June day from a dull
one. Measured end to end, out of fold, across 4-10 fold counts:

    stage 1 features                       chain skill vs persistence (mean)
    shortwave alone                        +0.239
    direct + diffuse + cloud               +0.232
    clear-sky index + envelope + cloud     +0.124
    direct + diffuse + cloud + day-of-year +0.069   (the old set)

Every seasonal variant lost, including an *exact* top-of-atmosphere envelope —
so this is not about the harmonic being a crude approximation.
"""

from datetime import UTC, date, datetime

import pytest

from wp6_data.red.dli.model import STAGE1_FEATURES, STAGE2_FEATURES
from wp6_data.red.dli.schedule import predict_natural_dli_from_weather
from wp6_data.shared.weather import DailyForecast, HourlyWeather

SEASONAL = ("day_of_year_sin", "day_of_year_cos", "terrestrial_sum", "clear_sky_index")


def _forecast(day: date, *, direct: float, diffuse: float) -> DailyForecast:
    return DailyForecast(
        date=day,
        hourly=[
            HourlyWeather(
                datetime=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                solar_radiation=(direct + diffuse) / 24,
                cloud_cover=50.0, temperature=10.0,
                direct_radiation=direct / 24, diffuse_radiation=diffuse / 24,
            )
            for hour in range(24)
        ],
    )


class _Recording:
    def __init__(self):
        self.calls = []

    def predict_dli(self, direct_radiation_sum=None, **kwargs):
        self.calls.append({"direct_radiation_sum": direct_radiation_sum, **kwargs})
        return 1.0


class TestFittedFeatureSets:
    def test_stage_1_carries_no_seasonal_feature(self):
        assert not set(STAGE1_FEATURES) & set(SEASONAL)

    def test_stage_1_is_global_irradiance_alone(self):
        assert STAGE1_FEATURES == ("shortwave_sum",)

    def test_stage_2_keeps_its_day_of_year_term(self):
        """The one place a seasonal feature earned its place: angle onto glass."""
        assert set(STAGE2_FEATURES) & {"day_of_year_sin", "day_of_year_cos"}


class TestServingSuppliesTheFittedFeature:
    def test_shortwave_sum_reaches_the_model(self):
        """A feature the model was fitted on and never served predicts nothing."""
        model = _Recording()
        forecast = _forecast(date(2026, 6, 21), direct=800.0, diffuse=400.0)

        predict_natural_dli_from_weather(model, [forecast])

        assert model.calls[0]["shortwave_sum"] == pytest.approx(1200.0)

    def test_it_is_the_global_total_not_the_beam(self):
        """Handing the beam sum to a shortwave slot is the v7 bug in reverse."""
        model = _Recording()
        forecast = _forecast(date(2025, 12, 10), direct=3.0, diffuse=272.0)

        predict_natural_dli_from_weather(model, [forecast])

        call = model.calls[0]
        assert call["shortwave_sum"] == pytest.approx(275.0)
        assert call["direct_radiation_sum"] == pytest.approx(3.0)
