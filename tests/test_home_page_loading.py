"""The home page's data loading: what it caches and what it runs concurrently.

Every home-page view reads devices, manual-upload freshness and export
metadata. These tests pin down the two properties that keep it fast: the
export metadata is not re-fetched from the object store per view, and the
three reads overlap instead of queueing.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from wp6_data.shared.export import (
    METADATA_KEY,
    clear_exports,
    get_export_metadata,
    write_export_metadata,
)
from wp6_data.shared.routes.home import load_home_data


class CountingStore:
    """In-memory store that counts metadata reads, or fails them on demand."""

    def __init__(self, metadata: dict | None = None, *, unreachable: bool = False):
        self.objects: dict[str, bytes] = {}
        if metadata is not None:
            self.objects[METADATA_KEY] = json.dumps(metadata).encode()
        self.unreachable = unreachable
        self.reads = 0

    async def put(self, key, data, *, content_type=None):
        self.objects[key] = data

    async def try_get(self, key):
        self.reads += 1
        if self.unreachable:
            raise ConnectionError("Could not connect to the endpoint URL")
        return self.objects.get(key)

    async def list(self, prefix=""):
        return list(self.objects)

    async def delete(self, *keys):
        for k in keys:
            self.objects.pop(k, None)
        return len(keys)


async def test_export_metadata_is_read_from_the_store_once():
    store = CountingStore({"devices": {"a": "t"}})

    first = await get_export_metadata(store)
    second = await get_export_metadata(store)

    assert first == second == {"devices": {"a": "t"}}
    assert store.reads == 1


async def test_unreachable_store_is_not_retried_on_every_view():
    """An outage should cost one slow request per TTL, not one per page view."""
    store = CountingStore(unreachable=True)

    assert await get_export_metadata(store) is None
    assert await get_export_metadata(store) is None
    assert store.reads == 1


async def test_writing_metadata_drops_the_cached_copy():
    store = CountingStore({"devices": {"old": "t"}})
    await get_export_metadata(store)

    await write_export_metadata(store, {"devices": {"new": "t"}})

    assert await get_export_metadata(store) == {"devices": {"new": "t"}}


async def test_clearing_exports_drops_the_cached_copy():
    store = CountingStore({"devices": {"a": "t"}})
    await get_export_metadata(store)

    await clear_exports(store)

    assert await get_export_metadata(store) is None


class InterlockedProvider:
    """Each fetch waits for the other to have started.

    Run sequentially, the first fetch would wait forever for the second; only
    concurrent execution lets both complete.
    """

    def __init__(self):
        self.devices_started = asyncio.Event()
        self.manual_started = asyncio.Event()

    async def fetch_device_data(self):
        self.devices_started.set()
        await self.manual_started.wait()
        return {"dev": {"sensors": [], "readings": 0, "last_seen": None}}

    async def fetch_manual_metadata(self):
        self.manual_started.set()
        await self.devices_started.wait()
        return {"uploads": {}, "measurements": {}}


async def test_home_data_fetches_run_concurrently():
    config = SimpleNamespace(export_store=CountingStore({"devices": {"dev": "t"}}))

    devices, manual, exports = await asyncio.wait_for(
        load_home_data(config, InterlockedProvider()), timeout=2,
    )

    assert list(devices) == ["dev"]
    assert manual == {"uploads": {}, "measurements": {}}
    assert exports == {"dev": "t"}


@pytest.mark.parametrize("metadata", [None, {"exported_at": "t"}])
async def test_home_data_without_exports_is_empty(metadata):
    config = SimpleNamespace(export_store=CountingStore(metadata))

    _, _, exports = await load_home_data(config, InterlockedProvider())

    assert exports == {}
