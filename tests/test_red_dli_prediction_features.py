"""The DLI model must be served the features it was fitted on (issues/053).

Stage 1 trains on beam radiation, measured diffuse and measured cloud cover. For
a long time every prediction handed it summed *shortwave* (direct + diffuse) in
the beam slot, 0.0 diffuse and a hardcoded 50% cloud. On an overcast December day
that is not a small error: 2025-12-10 had 3 Wh/m² of beam against 275 of
shortwave, so the beam feature was 92x its true value.
"""

from datetime import UTC, date, datetime

import pytest

from wp6_data.red.dli.model import TwoStageLightModel
from wp6_data.red.dli.schedule import predict_natural_dli_from_weather
from wp6_data.shared.weather import DailyForecast, HourlyWeather


def _forecast(day: date, *, direct: float, diffuse: float, cloud: float) -> DailyForecast:
    """A day whose 24 hours carry the given components, one 24th each."""
    return DailyForecast(
        date=day,
        hourly=[
            HourlyWeather(
                datetime=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                solar_radiation=(direct + diffuse) / 24,
                cloud_cover=cloud,
                temperature=10.0,
                direct_radiation=direct / 24,
                diffuse_radiation=diffuse / 24,
            )
            for hour in range(24)
        ],
    )


class RecordingModel:
    """Stands in for the trained model and records what it was served."""

    def __init__(self):
        self.calls = []

    def predict_dli(self, direct_radiation_sum, **kwargs):
        self.calls.append({"direct_radiation_sum": direct_radiation_sum, **kwargs})
        return 1.0


class TestServedFeatures:
    def test_beam_and_diffuse_are_passed_separately(self):
        model = RecordingModel()
        forecast = _forecast(date(2025, 12, 10), direct=3.0, diffuse=272.0, cloud=90.8)

        predict_natural_dli_from_weather(model, [forecast])

        call = model.calls[0]
        assert call["direct_radiation_sum"] == pytest.approx(3.0)
        assert call["diffuse_radiation_sum"] == pytest.approx(272.0)
        # ...and specifically NOT their sum, which is what used to be sent.
        assert call["direct_radiation_sum"] != pytest.approx(275.0)

    def test_measured_cloud_cover_is_passed_not_a_default(self):
        model = RecordingModel()
        forecast = _forecast(date(2025, 12, 10), direct=3.0, diffuse=272.0, cloud=90.8)

        predict_natural_dli_from_weather(model, [forecast])

        assert model.calls[0]["cloud_cover_avg"] == pytest.approx(90.8)

    def test_each_day_gets_its_own_day_of_year(self):
        """Defaulting to today froze the seasonal term across a whole hindcast."""
        model = RecordingModel()
        days = [date(2025, 12, 10), date(2026, 3, 1), date(2026, 6, 21)]
        forecasts = [_forecast(d, direct=100.0, diffuse=100.0, cloud=50.0) for d in days]

        predict_natural_dli_from_weather(model, forecasts)

        served = [c["day_of_year"] for c in model.calls]
        assert served == [d.timetuple().tm_yday for d in days]
        assert len(set(served)) == 3, "every day was given the same day-of-year"


class TestMissingFeaturesAreRefused:
    def _trained(self):
        model = TwoStageLightModel()
        model.stage1_features = [
            "direct_radiation_sum", "diffuse_radiation_sum", "cloud_cover_avg",
        ]
        model.stage2_features = ["lux_sum"]
        model.stage1_model = object()
        model.stage2_model = object()
        return model

    def test_a_fitted_feature_left_out_raises(self):
        """A stand-in value reads like a working prediction; an error does not."""
        model = self._trained()

        with pytest.raises(ValueError, match="cloud_cover_avg"):
            model.predict_daily(100.0, diffuse_radiation_sum=50.0)

    def test_the_error_names_every_missing_feature(self):
        model = self._trained()

        with pytest.raises(ValueError) as caught:
            model.predict_daily(100.0)

        message = str(caught.value)
        assert "diffuse_radiation_sum" in message
        assert "cloud_cover_avg" in message

    def test_a_feature_the_model_was_not_fitted_on_is_not_required(self):
        """Older models trained on radiation alone must still predict."""
        model = self._trained()
        model.stage1_features = ["direct_radiation_sum"]
        model.stage1_scaler = None
        model.stage1_poly = None

        class _Stage:
            def predict(self, _x):
                return [1000.0]

        model.stage1_model = _Stage()
        model.stage2_model = _Stage()
        model.stage2_features = ["lux_sum"]

        assert model.predict_daily(100.0) >= 0.0
