"""S3BlobStore against a real MinIO.

The LocalBlobStore unit tests pin the *contract*; these check that the S3
backend actually keeps it. That gap is where the interesting failures live:
botocore's error shapes, path-style addressing, pagination, and the difference
between "missing key" and "something is wrong".

Production storage is CloudStack's MinIO, so the container under test is the
same implementation -- not a stand-in that might diverge.
"""

import asyncio

import pytest

from tests.e2e.conftest import object_store_settings
from wp6_data.shared.blob import BlobNotFound, BlobStore, PrefixedBlobStore, S3BlobStore

pytestmark = pytest.mark.e2e


def test_s3_store_satisfies_the_protocol(s3_store):
    assert isinstance(s3_store, BlobStore)


@pytest.mark.asyncio
async def test_put_then_get_round_trips(s3_store):
    await s3_store.put("exports/s2100-01-par.csv", b"timestamp,value\n1,2\n")
    assert await s3_store.get("exports/s2100-01-par.csv") == b"timestamp,value\n1,2\n"


@pytest.mark.asyncio
async def test_bytes_survive_exactly(s3_store):
    """No encoding, no newline translation -- CSVs and pickles both ride this."""
    blob = bytes(range(256)) * 400
    await s3_store.put("models/climate_model.pkl", blob)
    assert await s3_store.get("models/climate_model.pkl") == blob


@pytest.mark.asyncio
async def test_get_raises_when_absent(s3_store):
    with pytest.raises(BlobNotFound):
        await s3_store.get("nope")


@pytest.mark.asyncio
async def test_try_get_returns_none_when_absent(s3_store):
    """The real reason this backend needs care: botocore signals 'missing' in
    more than one shape, and a caller must not see an exception for it."""
    assert await s3_store.try_get("nope") is None


@pytest.mark.asyncio
async def test_exists(s3_store):
    assert await s3_store.exists("k") is False
    await s3_store.put("k", b"x")
    assert await s3_store.exists("k") is True


@pytest.mark.asyncio
async def test_put_replaces_existing(s3_store):
    await s3_store.put("k", b"first")
    await s3_store.put("k", b"second")
    assert await s3_store.get("k") == b"second"


@pytest.mark.asyncio
async def test_list_returns_full_keys_sorted(s3_store):
    await s3_store.put("exports/b.csv", b"")
    await s3_store.put("exports/a.csv", b"")
    await s3_store.put("models/m.pkl", b"")

    assert await s3_store.list("exports/") == ["exports/a.csv", "exports/b.csv"]


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
async def test_delete_reports_how_many_existed(s3_store):
    await s3_store.put("a", b"")
    await s3_store.put("b", b"")

    assert await s3_store.delete("a", "b", "never-existed") == 2
    assert await s3_store.list("") == []


@pytest.mark.asyncio
async def test_delete_of_missing_key_is_not_an_error(s3_store):
    assert await s3_store.delete("nope") == 0


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


@pytest.mark.asyncio
async def test_unconfigured_store_refuses_to_construct():
    """An empty bucket means object storage is off, and callers fall back to
    disk. Constructing one anyway is a configuration error, not a silent
    no-op that would write nowhere."""
    with pytest.raises(ValueError, match="not configured"):
        S3BlobStore(object_store_settings(bucket=""))
