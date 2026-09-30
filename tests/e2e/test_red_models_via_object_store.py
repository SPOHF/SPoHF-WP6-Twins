"""Red's two models round-trip through a real S3, not just LocalBlobStore.

Phase 2 of issue 061. The unit tests pin the version/fingerprint gates against a
local store; these check the thing that actually changed — that a pickle written
through `write_pickled` comes back byte-identical over the S3 client, and that a
4MB-class artifact is a sane read at startup.

Both models share `shared.artifacts`, so the gates are exercised once here
rather than twice.
"""

import asyncio
import pickle
import time

import pytest

from wp6_data.shared.artifacts import read_pickled, write_pickled
from wp6_data.shared.blob import PrefixedBlobStore

pytestmark = pytest.mark.e2e

KEY = "climate_model.pkl"


@pytest.fixture
def models(s3_store):
    """Red's models corner of the bucket."""
    return PrefixedBlobStore(s3_store, "red/models")


@pytest.mark.asyncio
async def test_artifact_round_trips(models):
    payload = {"version": 2, "fingerprint": "abc", "chain": {"nested": [1, 2, 3]}}
    await write_pickled(models, KEY, payload)

    assert await read_pickled(models, KEY, version=2, expect_fingerprint="abc") == payload


@pytest.mark.asyncio
async def test_a_missing_artifact_reads_as_none(models):
    """A twin that has never trained is an ordinary state, not an error."""
    assert await read_pickled(models, KEY, version=2) is None


@pytest.mark.asyncio
async def test_an_older_version_is_refused(models):
    await write_pickled(models, KEY, {"version": 1, "chain": "x"})

    assert await read_pickled(models, KEY, version=2) is None


@pytest.mark.asyncio
async def test_a_different_fingerprint_is_refused(models):
    """The layout is fine; the question the model was fitted to answer moved."""
    await write_pickled(models, KEY, {"version": 2, "fingerprint": "old", "chain": "x"})

    assert await read_pickled(models, KEY, version=2, expect_fingerprint="new") is None


@pytest.mark.asyncio
async def test_a_corrupt_object_reads_as_none_rather_than_raising(models):
    """This runs during startup, where an exception is a failed boot."""
    await models.put(KEY, b"not a pickle at all")

    assert await read_pickled(models, KEY, version=2) is None


@pytest.mark.asyncio
async def test_a_pickle_naming_a_dead_module_reads_as_none(models):
    """The regression that motivated the broad except: the lamp model moved, and
    every saved artifact recorded its class by the old module path, so the load
    failed before the version inside could be consulted."""
    raw = b"\x80\x04cwp6_data.red.climate.lamp\nLampModel\n."
    with pytest.raises(ModuleNotFoundError):
        pickle.loads(raw)

    await models.put(KEY, raw)

    assert await read_pickled(models, KEY, version=2) is None


@pytest.mark.asyncio
async def test_a_realistic_artifact_is_a_sane_startup_read(models):
    """Red's climate chain is the largest artifact either twin stores.

    Timed because this read happens on the path to serving: it is backgrounded
    at startup, but a pathological cost here would show up as model-backed pages
    staying empty for a long time after a deploy.
    """
    payload = {
        "version": 2,
        "fingerprint": "abc",
        "blobs": [bytes(range(256)) * 4096 for _ in range(4)],  # ~4MB
    }
    await write_pickled(models, KEY, payload)

    started = time.monotonic()
    got = await read_pickled(models, KEY, version=2, expect_fingerprint="abc")
    elapsed = time.monotonic() - started

    assert got == payload
    assert elapsed < 30, f"4MB artifact read took {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_two_writers_do_not_tear_the_artifact(models):
    """The nightly refit can coincide with a deploy, and under RollingUpdate two
    pods overlap. A torn pickle would be served as a corrupt model."""
    a = {"version": 2, "fingerprint": "abc", "who": "A", "pad": b"A" * 500_000}
    b = {"version": 2, "fingerprint": "abc", "who": "B", "pad": b"B" * 500_000}

    await asyncio.gather(
        write_pickled(models, KEY, a), write_pickled(models, KEY, b),
    )

    assert await read_pickled(models, KEY, version=2, expect_fingerprint="abc") in (a, b)


@pytest.mark.asyncio
async def test_models_and_exports_do_not_collide(s3_store):
    """Separate prefixes: the nightly export clears its own corner wholesale, and
    sweeping up a model would be a very confusing outage."""
    models = PrefixedBlobStore(s3_store, "red/models")
    exports = PrefixedBlobStore(s3_store, "red/exports")

    await write_pickled(models, KEY, {"version": 2, "chain": "model"})
    await exports.put("s2100-01-par.csv", b"time,par\n")

    assert await models.list() == [KEY]
    assert await exports.list() == ["s2100-01-par.csv"]
