"""Export storage is a dependency, so its outage must not be the app's outage.

Issue 033's lesson, applied to the object store: an unreachable identity
provider once crash-looped both twins because startup pre-cached URLs it did
not yet need. Exports are decorative on the home page and optional everywhere
else, so a store that cannot be reached must degrade rather than propagate.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.export import csv_key, get_export_metadata, make_download_router


class UnreachableStore:
    """Every operation fails the way botocore fails with no route to the endpoint."""

    error = ConnectionError("Could not connect to the endpoint URL")

    async def put(self, key, data, *, content_type=None):
        raise self.error

    async def get(self, key):
        raise self.error

    async def try_get(self, key):
        raise self.error

    async def exists(self, key):
        raise self.error

    async def list(self, prefix=""):
        raise self.error

    async def delete(self, *keys):
        raise self.error


@pytest.mark.asyncio
async def test_metadata_reads_as_absent_when_store_is_unreachable():
    """The home page renders 'not yet available' instead of 500ing."""
    assert await get_export_metadata(UnreachableStore()) is None


@pytest.mark.asyncio
async def test_download_returns_503_not_404_when_store_is_unreachable():
    """404 would claim the export does not exist, sending the user after the
    wrong problem; the export may well be sitting in the bucket."""
    app = FastAPI()
    app.include_router(make_download_router(UnreachableStore()))
    app.dependency_overrides[verify_session_user] = lambda: "test-user"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/download/s2100-01-par")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_genuinely_missing_export_is_still_404():
    """The 503 path must not swallow the ordinary case."""

    class EmptyStore(UnreachableStore):
        async def try_get(self, key):
            return None

    app = FastAPI()
    app.include_router(make_download_router(EmptyStore()))
    app.dependency_overrides[verify_session_user] = lambda: "test-user"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/download/{csv_key('x').removesuffix('.csv')}")

    assert response.status_code == 404
