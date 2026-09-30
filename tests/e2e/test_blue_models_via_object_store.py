"""Blue's soil models round-trip through a real S3.

Blue's shape differs from red's in the way that matters here: N artifacts, one
per (sensor, treatment), *discovered by listing* rather than read from a known
key, with a separate stamp beside them saying what fitted them. Listing and
prefix filtering are the parts a local filesystem would not have tested
faithfully.

Phase 2 of issue 061.
"""

import json

import pytest

from wp6_data.blue.routes.monitor import soil_forecast
from wp6_data.blue.soil_forecaster import artifact_name
from wp6_data.shared.blob import PrefixedBlobStore

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


@pytest.fixture
def models(s3_store, monkeypatch):
    """Blue's models corner of the bucket, substituted into the route module."""
    store = PrefixedBlobStore(s3_store, "blue/models")
    monkeypatch.setattr(soil_forecast, "_models_store", lambda: store)
    return store


async def _fake_model(models, sensor="soilMoisture", treatment="K1"):
    await models.put(artifact_name(sensor, treatment), b"not really a pickle")


async def test_stored_models_are_discovered_by_listing(models):
    await _fake_model(models, "soilMoisture", "K1")
    await _fake_model(models, "soilTemperature", "Std")
    await soil_forecast._write_stamp()

    assert await soil_forecast._scan_models() == [
        "soilMoisture_K1.pkl",
        "soilTemperature_Std.pkl",
    ]


async def test_the_stamp_is_not_mistaken_for_a_model(models):
    """It sits beside them under the same prefix, so the filter is load-bearing."""
    await soil_forecast._write_stamp()

    assert await soil_forecast._scan_models() == []
    assert await models.exists(soil_forecast._STAMP_NAME)


async def test_models_without_a_stamp_are_treated_as_absent(models):
    await _fake_model(models)

    assert await soil_forecast._scan_models() == []


async def test_a_changed_configuration_invalidates_them(models, monkeypatch):
    await _fake_model(models)
    await soil_forecast._write_stamp()
    monkeypatch.setattr(
        soil_forecast, "_FORECAST_SENSORS",
        [*soil_forecast._FORECAST_SENSORS, "soilConductivity"],
    )

    assert await soil_forecast._scan_models() == []


async def test_a_corrupt_stamp_invalidates_rather_than_raises(models):
    await _fake_model(models)
    await models.put(soil_forecast._STAMP_NAME, b"{not json")

    assert await soil_forecast._scan_models() == []


async def test_the_stamp_round_trips_as_json(models):
    await soil_forecast._write_stamp()

    stamp = json.loads(await models.get(soil_forecast._STAMP_NAME))
    assert stamp["version"] == soil_forecast._ARTIFACT_VERSION
    assert stamp["fingerprint"]


async def test_clearing_removes_models_and_stamp_together(models):
    await _fake_model(models, "soilMoisture", "K1")
    await _fake_model(models, "soilTemperature", "Std")
    await soil_forecast._write_stamp()

    await soil_forecast._clear_models()

    assert await models.list() == []


async def test_a_retrain_drops_a_treatment_that_no_longer_qualifies(models):
    """A failed sensor, or too little growing-season data, must not leave last
    season's model serving — which is why the store is cleared before writing."""
    await _fake_model(models, "soilMoisture", "GoneAway")
    await soil_forecast._write_stamp()

    await soil_forecast._clear_models()
    await _fake_model(models, "soilMoisture", "StillHere")
    await soil_forecast._write_stamp()

    assert await soil_forecast._scan_models() == ["soilMoisture_StillHere.pkl"]


async def test_a_model_that_will_not_unpickle_is_skipped_not_fatal(models, caplog):
    """The stamp cannot see every kind of drift, so a broken artifact is the last
    signal one happened — logged loudly, and the other models still load."""
    await models.put(artifact_name("soilMoisture", "Broken"), b"not a pickle")

    loaded = await soil_forecast._load_models(["soilMoisture_Broken.pkl"])

    assert loaded == {}
    assert "failed to load model" in caplog.text


async def test_blue_models_do_not_collide_with_red_or_with_exports(s3_store):
    """One bucket, four prefixes."""
    blue_models = PrefixedBlobStore(s3_store, "blue/models")
    red_models = PrefixedBlobStore(s3_store, "red/models")
    blue_exports = PrefixedBlobStore(s3_store, "blue/exports")

    await blue_models.put("soilMoisture_K1.pkl", b"blue model")
    await red_models.put("light_model.pkl", b"red model")
    await blue_exports.put("weatherstation.csv", b"time,value\n")

    assert await blue_models.list() == ["soilMoisture_K1.pkl"]
    assert await red_models.list() == ["light_model.pkl"]
    assert await blue_exports.list() == ["weatherstation.csv"]
