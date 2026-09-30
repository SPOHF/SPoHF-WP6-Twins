"""Blue's soil models had no staleness gate at all until they began to persist.

While they lived on ephemeral storage that was survivable: a restart wiped them
and the dashboard refitted. Keeping them across a deploy means an artifact can
now outlive the code that wrote it, so something has to say which code and
configuration produced it.

The models moved to the object store (issue 061 phase 2), so the stamp is a blob
beside them rather than a file in a directory. The gate is the same.
"""

import json

import pytest

from wp6_data.blue.routes.monitor import soil_forecast
from wp6_data.shared.blob import LocalBlobStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Substitute the models store, so nothing touches a real bucket."""
    local = LocalBlobStore(tmp_path)
    monkeypatch.setattr(soil_forecast, "_models_store", lambda: local)
    return local


async def _fake_model(store, name="soilMoisture_K1.pkl"):
    await store.put(name, b"not really a pickle")


class TestStamp:
    async def test_models_without_a_stamp_are_treated_as_absent(self, store):
        """Artifacts from before stamping existed cannot be vouched for, and
        refitting is the cheap, safe answer."""
        await _fake_model(store)

        assert await soil_forecast._scan_models() == []

    async def test_a_matching_stamp_makes_them_usable(self, store):
        await _fake_model(store)
        await soil_forecast._write_stamp()

        assert len(await soil_forecast._scan_models()) == 1

    async def test_a_version_bump_invalidates_them(self, store, monkeypatch):
        await _fake_model(store)
        await soil_forecast._write_stamp()
        monkeypatch.setattr(
            soil_forecast, "_ARTIFACT_VERSION", soil_forecast._ARTIFACT_VERSION + 1
        )

        assert await soil_forecast._scan_models() == []

    async def test_changing_which_sensors_are_modelled_invalidates_them(
        self, store, monkeypatch
    ):
        """The models are fitted per sensor, so the sensor list is part of what
        produced them — a config change the version constant cannot see."""
        await _fake_model(store)
        await soil_forecast._write_stamp()
        monkeypatch.setattr(
            soil_forecast, "_FORECAST_SENSORS",
            [*soil_forecast._FORECAST_SENSORS, "soilConductivity"],
        )

        assert await soil_forecast._scan_models() == []

    async def test_a_corrupt_stamp_invalidates_rather_than_raises(self, store):
        await _fake_model(store)
        await store.put(soil_forecast._STAMP_NAME, b"{not json")

        assert await soil_forecast._scan_models() == []

    async def test_an_empty_store_needs_no_stamp(self, store):
        """Nothing stored is 'not trained', which the pages already say."""
        assert await soil_forecast._scan_models() == []
        assert await store.exists(soil_forecast._STAMP_NAME) is False

    async def test_the_stamp_records_a_fingerprint_not_just_a_number(self, store):
        await soil_forecast._write_stamp()
        stamp = json.loads(await store.get(soil_forecast._STAMP_NAME))

        assert stamp["version"] == soil_forecast._ARTIFACT_VERSION
        assert stamp["fingerprint"]

    async def test_only_pkl_objects_count_as_models(self, store):
        """The stamp lives beside them, and must not be mistaken for a model."""
        await soil_forecast._write_stamp()

        assert await soil_forecast._scan_models() == []


class TestUnreachableStore:
    """An outage must not 500 the page whose job is to say whether models exist."""

    async def test_scan_reads_as_no_models(self, monkeypatch):
        class Broken:
            async def list(self, prefix=""):
                raise ConnectionError("no route to endpoint")

        monkeypatch.setattr(soil_forecast, "_models_store", lambda: Broken())

        assert await soil_forecast._scan_models() == []
