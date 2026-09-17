"""Blue's soil models had no staleness gate at all until they began to persist.

While they lived on ephemeral storage that was survivable: a restart wiped them
and the dashboard refitted. Keeping them across a deploy means an artifact can
now outlive the code that wrote it, so something has to say which code and
configuration produced it.
"""

import json

import pytest

from wp6_data.blue.routes.monitor import soil_forecast


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(soil_forecast, "_MODELS_DIR", tmp_path)
    return tmp_path


def _fake_model(directory, name="soilMoisture_K1.pkl"):
    (directory / name).write_bytes(b"not really a pickle")


class TestStamp:
    def test_models_without_a_stamp_are_treated_as_absent(self, models_dir):
        """Artifacts from before stamping existed cannot be vouched for, and
        refitting is the cheap, safe answer."""
        _fake_model(models_dir)

        assert soil_forecast._scan_models() == []

    def test_a_matching_stamp_makes_them_usable(self, models_dir):
        _fake_model(models_dir)
        soil_forecast._write_stamp()

        assert len(soil_forecast._scan_models()) == 1

    def test_a_version_bump_invalidates_them(self, models_dir, monkeypatch):
        _fake_model(models_dir)
        soil_forecast._write_stamp()
        monkeypatch.setattr(
            soil_forecast, "_ARTIFACT_VERSION", soil_forecast._ARTIFACT_VERSION + 1
        )

        assert soil_forecast._scan_models() == []

    def test_changing_which_sensors_are_modelled_invalidates_them(
        self, models_dir, monkeypatch
    ):
        """The models are fitted per sensor, so the sensor list is part of what
        produced them — a config change the version constant cannot see."""
        _fake_model(models_dir)
        soil_forecast._write_stamp()
        monkeypatch.setattr(
            soil_forecast, "_FORECAST_SENSORS",
            [*soil_forecast._FORECAST_SENSORS, "soilConductivity"],
        )

        assert soil_forecast._scan_models() == []

    def test_a_corrupt_stamp_invalidates_rather_than_raises(self, models_dir):
        _fake_model(models_dir)
        (models_dir / soil_forecast._STAMP_NAME).write_text("{not json")

        assert soil_forecast._scan_models() == []

    def test_an_empty_directory_needs_no_stamp(self, models_dir):
        """Nothing on disk is 'not trained', which the pages already say."""
        assert soil_forecast._scan_models() == []
        assert not (models_dir / soil_forecast._STAMP_NAME).exists()

    def test_the_stamp_records_a_fingerprint_not_just_a_number(self, models_dir):
        soil_forecast._write_stamp()
        stamp = json.loads((models_dir / soil_forecast._STAMP_NAME).read_text())

        assert stamp["version"] == soil_forecast._ARTIFACT_VERSION
        assert stamp["fingerprint"]
