"""LocalBlobStore behaviour, and the contract both backends must keep.

The S3 backend is exercised against the real store by the probe harness in
issue 061; these tests pin the semantics the interface promises, so a second
backend has something to be checked against.
"""

import asyncio

import pytest

from wp6_data.config import ObjectStoreSettings
from wp6_data.shared.blob import (
    BlobNotFound,
    BlobStore,
    LocalBlobStore,
    PrefixedBlobStore,
    make_store,
)


@pytest.fixture
def store(tmp_path):
    return LocalBlobStore(tmp_path / "blobs")


def test_local_store_satisfies_the_protocol(store):
    assert isinstance(store, BlobStore)


@pytest.mark.asyncio
async def test_put_then_get_round_trips(store):
    await store.put("exports/s2100-01-par.csv", b"timestamp,value\n")
    assert await store.get("exports/s2100-01-par.csv") == b"timestamp,value\n"


@pytest.mark.asyncio
async def test_put_creates_missing_parents(store):
    """Keys are not paths -- nothing creates the 'directory' first."""
    await store.put("a/deeply/nested/key.bin", b"x")
    assert await store.exists("a/deeply/nested/key.bin")


@pytest.mark.asyncio
async def test_put_replaces_existing(store):
    await store.put("k", b"first")
    await store.put("k", b"second")
    assert await store.get("k") == b"second"


@pytest.mark.asyncio
async def test_get_raises_when_absent(store):
    with pytest.raises(BlobNotFound):
        await store.get("nope")


@pytest.mark.asyncio
async def test_try_get_returns_none_when_absent(store):
    assert await store.try_get("nope") is None


@pytest.mark.asyncio
async def test_exists(store):
    assert await store.exists("k") is False
    await store.put("k", b"x")
    assert await store.exists("k") is True


@pytest.mark.asyncio
async def test_list_returns_full_keys_sorted(store):
    await store.put("exports/b.csv", b"")
    await store.put("exports/a.csv", b"")
    await store.put("models/m.pkl", b"")

    assert await store.list("exports/") == ["exports/a.csv", "exports/b.csv"]


@pytest.mark.asyncio
async def test_list_keys_are_usable_as_arguments(store):
    """The point of returning full keys: feed them straight back in."""
    await store.put("exports/a.csv", b"data")
    (key,) = await store.list("exports/")
    assert await store.get(key) == b"data"


@pytest.mark.asyncio
async def test_list_of_missing_prefix_is_empty(store):
    assert await store.list("nothing/") == []


@pytest.mark.asyncio
async def test_list_on_empty_store_is_empty(store):
    """The root may not exist yet -- listing must not raise."""
    assert await store.list("") == []


@pytest.mark.asyncio
async def test_delete_reports_how_many_existed(store):
    await store.put("a", b"")
    await store.put("b", b"")

    assert await store.delete("a", "b", "never-existed") == 2
    assert await store.list("") == []


@pytest.mark.asyncio
async def test_delete_of_missing_key_is_not_an_error(store):
    assert await store.delete("nope") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    ["../escape", "exports/../../escape", "/etc/passwd"],
)
async def test_keys_cannot_escape_the_root(store, key):
    """The download route takes a user-supplied name, so traversal must fail loudly."""
    with pytest.raises(ValueError, match="escapes store root"):
        await store.put(key, b"x")


@pytest.mark.asyncio
async def test_put_is_atomic_under_concurrent_writers(store):
    """A reader sees one whole value, never a mix of two.

    The probe confirmed MinIO gives last-writer-wins on a concurrent PUT; the
    local backend keeps the same promise via write-then-rename, so code written
    against one backend behaves the same on the other.
    """
    a, b = b"A" * 200_000, b"B" * 200_000
    await asyncio.gather(store.put("race", a), store.put("race", b))

    assert await store.get("race") in (a, b)


@pytest.mark.asyncio
async def test_temp_files_are_not_listed(store):
    """write-then-rename leaves dotfiles mid-flight; they are not blobs."""
    await store.put("exports/a.csv", b"data")
    assert await store.list("") == ["exports/a.csv"]


# --- PrefixedBlobStore -------------------------------------------------------
# One bucket holds every twin's exports, models and uploads, separated by key
# prefix. These pin that mapping, because a wrong prefix silently writes into
# another twin's namespace rather than failing.


@pytest.fixture
def red_exports(store):
    return PrefixedBlobStore(store, "red/exports")


def test_prefixed_store_satisfies_the_protocol(red_exports):
    assert isinstance(red_exports, BlobStore)


@pytest.mark.asyncio
async def test_prefix_is_applied_to_the_underlying_key(red_exports, store):
    await red_exports.put("s2100-01-par.csv", b"data")
    assert await store.get("red/exports/s2100-01-par.csv") == b"data"


@pytest.mark.asyncio
async def test_trailing_slash_is_optional(store):
    with_slash = PrefixedBlobStore(store, "red/exports/")
    without = PrefixedBlobStore(store, "red/exports")

    await with_slash.put("a.csv", b"x")
    assert await without.get("a.csv") == b"x"


@pytest.mark.asyncio
async def test_list_returns_keys_relative_to_the_prefix(red_exports):
    await red_exports.put("a.csv", b"")
    await red_exports.put("b.csv", b"")

    assert await red_exports.list() == ["a.csv", "b.csv"]


@pytest.mark.asyncio
async def test_twins_do_not_see_each_other(store):
    """The whole point of one bucket with prefixes."""
    red = PrefixedBlobStore(store, "red/exports")
    blue = PrefixedBlobStore(store, "blue/exports")

    await red.put("device.csv", b"red data")
    await blue.put("device.csv", b"blue data")

    assert await red.get("device.csv") == b"red data"
    assert await blue.get("device.csv") == b"blue data"
    assert await red.list() == ["device.csv"]
    assert await blue.list() == ["device.csv"]


@pytest.mark.asyncio
async def test_delete_is_scoped_to_the_prefix(store):
    red = PrefixedBlobStore(store, "red/exports")
    blue = PrefixedBlobStore(store, "blue/exports")
    await red.put("device.csv", b"")
    await blue.put("device.csv", b"")

    assert await red.delete("device.csv") == 1
    assert await red.list() == []
    assert await blue.list() == ["device.csv"]


@pytest.mark.asyncio
async def test_missing_key_error_does_not_leak_the_prefix(red_exports):
    """The prefix is the wrapper's business; an error naming it confuses callers."""
    with pytest.raises(BlobNotFound) as excinfo:
        await red_exports.get("nope.csv")

    assert excinfo.value.args[0] == "nope.csv"


# --- make_store: no silent fallback -----------------------------------------


def test_make_store_refuses_when_not_configured():
    """A missing bucket is our misconfiguration, and it never self-heals.

    The earlier version returned a LocalBlobStore here, and that silence was
    the bug: the export job wrote to a directory while the dashboard read an
    empty bucket, and nothing said why. Per issue 033, configuration errors
    crash loudly; only dependency outages degrade.
    """
    with pytest.raises(RuntimeError, match="not configured"):
        make_store(ObjectStoreSettings(bucket=""), prefix="red/exports")


def test_make_store_error_names_the_setting_and_the_local_fix():
    """The message has to be actionable -- this is the first thing a developer
    or a crash-looping pod shows."""
    with pytest.raises(RuntimeError) as excinfo:
        make_store(ObjectStoreSettings(bucket=""), prefix="red/exports")

    message = str(excinfo.value)
    assert "WP6_S3_BUCKET" in message
    assert ".env" in message
    assert "docker compose" in message


def test_make_store_applies_the_prefix_when_configured():
    store = make_store(
        ObjectStoreSettings(
            bucket="spohf",
            endpoint_url="http://localhost:9100",
            access_key_id="k",
            secret_access_key="s",
        ),
        prefix="red/exports",
    )

    assert isinstance(store, PrefixedBlobStore)
    assert store.prefix == "red/exports/"
    assert store.inner.bucket == "spohf"
