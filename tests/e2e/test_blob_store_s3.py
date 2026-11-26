"""S3BlobStore against the s3mock container.

The LocalBlobStore unit tests pin the *contract* for every backend; what
remains here is only what the S3 wire path adds on top: botocore's error
shapes, pagination past the 1000-key page, byte fidelity over HTTP, and
last-writer-wins under concurrent writers. Everything else (round trip,
exists, replace, delete counting, unconfigured-refuses) is pure contract
and already covered against LocalBlobStore in tests/test_blob_store.py.

Note the container is adobe/s3mock, a mock, not production's MinIO -- see
docker-compose.tsdb.yml for why. So this validates OUR CLIENT against the
S3 API shapes, not MinIO's behaviour.
"""

import asyncio

import pytest

from wp6_data.shared.blob import BlobStore, PrefixedBlobStore

pytestmark = pytest.mark.e2e


def test_s3_store_satisfies_the_protocol(s3_store):
    assert isinstance(s3_store, BlobStore)


@pytest.mark.asyncio
async def test_bytes_survive_exactly(s3_store):
    """No encoding, no newline translation -- CSVs and pickles both ride this."""
    blob = bytes(range(256)) * 400
    await s3_store.put("models/climate_model.pkl", blob)
    assert await s3_store.get("models/climate_model.pkl") == blob


@pytest.mark.asyncio
async def test_try_get_returns_none_when_absent(s3_store):
    """The real reason this backend needs care: botocore signals 'missing' in
    more than one shape, and a caller must not see an exception for it."""
    assert await s3_store.try_get("nope") is None


@pytest.mark.asyncio
async def test_list_paginates_beyond_one_page(s3_store):
    """list_objects_v2 caps at 1000 keys per response.

    A twin's export set is far smaller than this today, but a silent truncation
    would mean `clear_export_dir`'s successor leaving stale CSVs behind rather
    than failing -- exactly the kind of bug that surfaces months later as a
    download serving last quarter's data.
    """
    await asyncio.gather(*(s3_store.put(f"many/{i:05d}.csv", b"x") for i in range(1050)))

    assert len(await s3_store.list("many/")) == 1050


@pytest.mark.asyncio
async def test_concurrent_put_is_atomic(s3_store):
    """Two pods can overlap during a RollingUpdate surge, and the nightly
    refit can coincide with a deploy. A torn object would be served as a
    corrupt model; the probe showed the real store gives last-writer-wins,
    and this keeps that honest against the client code we actually ship."""
    a, b = b"A" * 2_000_000, b"B" * 2_000_000
    await asyncio.gather(s3_store.put("race", a), s3_store.put("race", b))

    assert await s3_store.get("race") in (a, b)


@pytest.mark.asyncio
async def test_prefixed_view_isolates_twins(s3_store):
    """One bucket serves both twins; the prefix is the only separation."""
    red = PrefixedBlobStore(s3_store, "red/exports")
    blue = PrefixedBlobStore(s3_store, "blue/exports")

    await red.put("device.csv", b"red data")
    await blue.put("device.csv", b"blue data")

    assert await red.get("device.csv") == b"red data"
    assert await blue.get("device.csv") == b"blue data"
    assert await red.list() == ["device.csv"]
