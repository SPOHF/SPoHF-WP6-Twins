"""The export round trip: job writes to the store, dashboard serves from it.

This is the phase-1 claim of issue 061 -- that exports can live in the bucket
instead of on a ReadWriteOnce PVC -- checked against a real MinIO rather than
against LocalBlobStore, so the S3 semantics are the ones under test.

It deliberately goes through the shared helpers the twins call
(`clear_exports`, `write_export_metadata`, `get_export_metadata`,
`make_download_router`) rather than poking the store directly.
"""

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.blob import PrefixedBlobStore
from wp6_data.shared.export import (
    METADATA_KEY,
    clear_exports,
    csv_key,
    get_export_metadata,
    make_download_router,
    sanitise_name,
    write_export_metadata,
)

pytestmark = pytest.mark.e2e

CSV_BODY = "time,par\n2026-09-22T00:00:00Z,1.5\n"


async def _client(store, *, sanitise: bool = False) -> AsyncClient:
    """A dashboard-shaped app carrying only the download router.

    The route is authenticated, which is its own property and has its own
    tests; here it is overridden so a failure points at the export path rather
    than at session plumbing.
    """
    app = FastAPI()
    app.include_router(make_download_router(store, sanitise=sanitise))
    app.dependency_overrides[verify_session_user] = lambda: "e2e-user"
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def red_exports(s3_store):
    return PrefixedBlobStore(s3_store, "red/exports")


@pytest.mark.asyncio
async def test_export_is_written_then_downloaded(red_exports):
    """The whole point: a nightly job writes, a web request serves it back."""
    await red_exports.put(csv_key("s2100-01-par"), CSV_BODY.encode())
    await write_export_metadata(
        red_exports, {"exported_at": "2026-09-22T02:00:00Z", "devices": {"s2100-01-par": "t"}}
    )

    async with await _client(red_exports) as client:
        response = await client.get("/download/s2100-01-par")

    assert response.status_code == 200
    assert response.text == CSV_BODY
    assert response.headers["content-type"].startswith("text/csv")
    assert "s2100-01-par.csv" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_of_missing_export_is_404(red_exports):
    async with await _client(red_exports) as client:
        response = await client.get("/download/never-exported")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metadata_round_trips(red_exports):
    metadata = {"exported_at": "2026-09-22T02:00:00Z", "devices": {"a": "t1", "b": "t2"}}
    await write_export_metadata(red_exports, metadata)

    assert await get_export_metadata(red_exports) == metadata


@pytest.mark.asyncio
async def test_metadata_is_none_before_the_first_export(red_exports):
    """A twin that has never exported renders 'not yet available', not an error."""
    assert await get_export_metadata(red_exports) is None


@pytest.mark.asyncio
async def test_corrupt_metadata_reads_as_absent(red_exports):
    """A half-written metadata file must degrade, not 500 the home page."""
    await red_exports.put(METADATA_KEY, b"{not json")

    assert await get_export_metadata(red_exports) is None


@pytest.mark.asyncio
async def test_clear_removes_csvs_and_metadata(red_exports):
    await red_exports.put(csv_key("a"), CSV_BODY.encode())
    await red_exports.put(csv_key("b"), CSV_BODY.encode())
    await write_export_metadata(red_exports, {"devices": {}})

    assert await clear_exports(red_exports) == 3
    assert await red_exports.list() == []


@pytest.mark.asyncio
async def test_clear_leaves_unexpected_objects_alone(red_exports):
    """A nightly job silently deleting something nobody expected is worse than
    leaving it for a human to notice."""
    await red_exports.put(csv_key("a"), CSV_BODY.encode())
    await red_exports.put("README.txt", b"why is this here")

    assert await clear_exports(red_exports) == 1
    assert await red_exports.list() == ["README.txt"]


@pytest.mark.asyncio
async def test_clear_on_empty_store_is_zero(red_exports):
    assert await clear_exports(red_exports) == 0


@pytest.mark.asyncio
async def test_blue_device_names_are_flattened(s3_store):
    """Blue names carry '/' and spaces; unflattened they would create
    accidental key hierarchy in the bucket."""
    blue = PrefixedBlobStore(s3_store, "blue/exports")
    device = "Tunnel 3/Row A"

    await blue.put(csv_key(sanitise_name(device)), CSV_BODY.encode())

    assert await blue.list() == ["Tunnel_3_Row_A.csv"]

    async with await _client(blue, sanitise=True) as client:
        response = await client.get(f"/download/{device}")

    assert response.status_code == 200
    assert response.text == CSV_BODY


@pytest.mark.asyncio
async def test_twins_exports_do_not_collide(s3_store):
    """Both twins export a device called the same thing into one bucket."""
    red = PrefixedBlobStore(s3_store, "red/exports")
    blue = PrefixedBlobStore(s3_store, "blue/exports")

    await red.put(csv_key("shared-name"), b"red rows")
    await blue.put(csv_key("shared-name"), b"blue rows")

    async with await _client(red) as red_client:
        assert (await red_client.get("/download/shared-name")).text == "red rows"
    async with await _client(blue) as blue_client:
        assert (await blue_client.get("/download/shared-name")).text == "blue rows"


@pytest.mark.asyncio
async def test_a_rerun_replaces_rather_than_accumulates(red_exports):
    """The nightly job clears first, so a device that stops reporting does not
    keep serving last week's CSV."""
    await red_exports.put(csv_key("gone-tomorrow"), CSV_BODY.encode())
    await write_export_metadata(red_exports, {"devices": {"gone-tomorrow": "t"}})

    await clear_exports(red_exports)
    await red_exports.put(csv_key("still-here"), CSV_BODY.encode())
    await write_export_metadata(red_exports, {"devices": {"still-here": "t"}})

    assert sorted(await red_exports.list()) == [METADATA_KEY, csv_key("still-here")]
    meta = await get_export_metadata(red_exports)
    assert json.dumps(meta["devices"]) == json.dumps({"still-here": "t"})
