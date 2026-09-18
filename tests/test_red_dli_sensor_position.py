"""A DLI prediction must say which sensor position it is for.

Stage 2 is fitted on ``NATURAL_LIGHT_SENSOR``, which hangs *above* the lamps, and
the attenuation factor converts that to the plant-level position under them. The
conversion used to be applied unconditionally inside ``predict_daily``, so
``/dli/performance`` scored a plant-level prediction against the above-lamp
sensor. Nothing was wrong with the model; the page reported a systematic
underprediction of the entire attenuation factor — around 38% — because the two
sides of the comparison were different physical quantities.
"""

from datetime import UTC, date, datetime

import pytest

from wp6_data.red.dli.model import TwoStageLightModel
from wp6_data.red.dli.schedule import predict_natural_dli_from_weather
from wp6_data.shared.weather import DailyForecast, HourlyWeather

# The factor red's model actually fits (MODEL_PAPER §7.3 reports a median of
# 0.622). The exact value does not matter here — that the two positions differ
# by it, and only by it, does.
ATTENUATION = 0.622
ABOVE_LAMP_PAR_SUM = 100_000.0


class _Stage:
    """A fitted stage that always predicts the same value."""

    def __init__(self, value: float):
        self.value = value

    def predict(self, _x):
        return [self.value]


def _model() -> TwoStageLightModel:
    """A trained-looking model whose stage 2 emits a known above-lamp PAR sum."""
    model = TwoStageLightModel()
    model.stage1_features = ["direct_radiation_sum"]
    model.stage2_features = ["lux_sum"]
    model.stage1_model = _Stage(5000.0)
    model.stage2_model = _Stage(ABOVE_LAMP_PAR_SUM)
    model.stage1_scaler = None
    model.stage2_scaler = None
    model.stage1_poly = None
    model.stage2_poly = None
    model.attenuation_factor = ATTENUATION
    return model


def _forecast(day: date) -> DailyForecast:
    """A day carrying enough weather for stage 1's fitted features."""
    return DailyForecast(
        date=day,
        hourly=[
            HourlyWeather(
                datetime=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                solar_radiation=10.0,
                cloud_cover=50.0,
                temperature=10.0,
                direct_radiation=5.0,
                diffuse_radiation=5.0,
            )
            for hour in range(24)
        ],
    )


class TestSensorPosition:
    def test_above_lamp_prediction_is_not_attenuated(self):
        """What stage 2 was fitted on comes back unchanged."""
        assert _model().predict_daily(
            100.0, at_plant_level=False
        ) == pytest.approx(ABOVE_LAMP_PAR_SUM)

    def test_plant_level_prediction_applies_attenuation(self):
        assert _model().predict_daily(
            100.0, at_plant_level=True
        ) == pytest.approx(ABOVE_LAMP_PAR_SUM * ATTENUATION)

    def test_the_two_positions_differ_by_exactly_the_attenuation_factor(self):
        """The bug, stated directly: one is the other times the factor."""
        model = _model()
        above = model.predict_daily(100.0, at_plant_level=False)
        plant = model.predict_daily(100.0, at_plant_level=True)

        assert plant / above == pytest.approx(ATTENUATION)

    def test_plant_level_is_the_default(self):
        """The grower-facing pages ask about light reaching the plants."""
        model = _model()

        assert model.predict_daily(100.0) == pytest.approx(
            model.predict_daily(100.0, at_plant_level=True)
        )


class TestScheduleHelperPassesThePositionThrough:
    def test_the_position_reaches_the_model(self):
        """`/dli/performance` selects the position here, so it must not be dropped."""
        model = _model()
        forecasts = [_forecast(date(2026, 3, 1))]

        above = predict_natural_dli_from_weather(model, forecasts, at_plant_level=False)
        plant = predict_natural_dli_from_weather(model, forecasts, at_plant_level=True)

        day = date(2026, 3, 1)
        assert plant[day] / above[day] == pytest.approx(ATTENUATION)

    def test_default_matches_the_model_default(self):
        model = _model()
        forecasts = [_forecast(date(2026, 3, 1))]

        assert predict_natural_dli_from_weather(model, forecasts) == (
            predict_natural_dli_from_weather(model, forecasts, at_plant_level=True)
        )
