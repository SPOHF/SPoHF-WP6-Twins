"""E2E: Blue incremental sync → Neo4j → dashboard renders the data."""

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from httpx import ASGITransport

from wp6_data.config import Settings
from wp6_data.sync.orchestrator import SyncOrchestrator

pytestmark = pytest.mark.e2e

# ── Test data ────────────────────────────────────────────────────────

FAKE_API_URL = "https://e2e-fake-api.test"
ENDPOINT = "e2e-yookr"
PROJECT = "e2e-project"
DEVICES = {
    "e2e-device-alpha": "e2e-sensor-id-alpha",
    "e2e-device-beta": "e2e-sensor-id-beta",
}
SENSORS = {
    "e2e-temperature": "21.5",
    "e2e-humidity": "65.0",
}

NOW = datetime.now(UTC)


def _build_fake_readings() -> list[dict]:
    """Build ~10 fake readings as JSON-serialisable dicts (what the API returns)."""
    readings = []
    i = 0
    for device_name, sensor_id in DEVICES.items():
        for tag, value in SENSORS.items():
            ts = NOW - timedelta(hours=i + 1)
            readings.append(
                {
                    "sensor_id": sensor_id,
                    "project": PROJECT,
                    "device_name": device_name,
                    "sensor_tag": tag,
                    "value": value,
                    "datetime_measure": ts.isoformat(),
                    "timestamp": ts.isoformat(),
                }
            )
            i += 1
    # Add a few extra temperature readings for device-alpha
    for j in range(2):
        ts = NOW - timedelta(hours=10 + j)
        readings.append(
            {
                "sensor_id": DEVICES["e2e-device-alpha"],
                "project": PROJECT,
                "device_name": "e2e-device-alpha",
                "sensor_tag": "e2e-temperature",
                "value": str(21.5 + j * 0.1),
                "datetime_measure": ts.isoformat(),
                "timestamp": ts.isoformat(),
            }
        )
    return readings


FAKE_READINGS = _build_fake_readings()

# ── Helpers ──────────────────────────────────────────────────────────


def _make_settings() -> Settings:
    """Build a real Settings object pointed at localhost Neo4j + fake API."""
    return Settings(
        api_base_url=FAKE_API_URL,
        api_token="e2e-dummy-token",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="localdevpassword",
        neo4j_database="neo4j",
        sync_mode="incremental",
        sync_page_size=100,
        sync_window_days=1,
        endpoints=ENDPOINT,
    )


def _api_handler(request: httpx.Request) -> httpx.Response:
    """Return fake readings on first window, empty on subsequent ones."""
    # The client uses 'from' param as offset for pagination
    offset = int(request.url.params.get("from", "0"))
    if not hasattr(_api_handler, "_windows_served"):
        _api_handler._windows_served = 0

    if offset > 0:
        # Second page of any window → empty (no more pages)
        return httpx.Response(200, json={"results": [], "count": 0})

    _api_handler._windows_served += 1
    if _api_handler._windows_served == 1:
        # First window: return all fake data
        return httpx.Response(
            200,
            json={"results": FAKE_READINGS, "count": len(FAKE_READINGS)},
        )
    # Subsequent windows: empty
    return httpx.Response(200, json={"results": [], "count": 0})


# ── The test ─────────────────────────────────────────────────────────


@pytest.mark.e2e
async def test_incremental_sync_and_dashboard_display(neo4j_driver):
    """Full pipeline: mock API → sync → Neo4j state → dashboard HTTP."""

    # Reset handler state
    _api_handler._windows_served = 0

    settings = _make_settings()

    # ── 1. Sync with mocked API ──────────────────────────────────────
    with respx.mock(base_url=FAKE_API_URL) as respx_mock:
        respx_mock.get(url__regex=r"/api/v1/data/.*").mock(side_effect=_api_handler)

        orchestrator = SyncOrchestrator(settings)
        stats = await orchestrator.run()

    # ── 2. Assert sync results ───────────────────────────────────────
    assert stats["total_records"] > 0, f"Expected records, got: {stats}"
    assert stats["errors"] == [], f"Sync errors: {stats['errors']}"

    # ── 3. Assert Neo4j state ────────────────────────────────────────
    async with neo4j_driver.session() as session:
        # Device nodes
        result = await session.run(
            "MATCH (d:Device) WHERE d.device_name STARTS WITH 'e2e-' "
            "RETURN d.device_name AS name ORDER BY name"
        )
        devices = [r["name"] async for r in result]
        assert "e2e-device-alpha" in devices
        assert "e2e-device-beta" in devices

        # Sensor nodes
        result = await session.run(
            "MATCH (s:Sensor) WHERE s.tag STARTS WITH 'e2e-' "
            "RETURN DISTINCT s.tag AS tag ORDER BY tag"
        )
        tags = [r["tag"] async for r in result]
        assert "e2e-temperature" in tags
        assert "e2e-humidity" in tags

        # Reading nodes with expected values
        result = await session.run(
            "MATCH (s:Sensor {tag: 'e2e-temperature'})-[:RECORDED]->(r:Reading) "
            "RETURN r.raw_value AS val"
        )
        values = [r["val"] async for r in result]
        assert "21.5" in values

        # DailyCoverage nodes
        result = await session.run(
            "MATCH (c:DailyCoverage) WHERE c.device_name STARTS WITH 'e2e-' "
            "RETURN count(c) AS cnt"
        )
        record = await result.single()
        assert record["cnt"] > 0, "Expected DailyCoverage nodes"

        # SyncMetadata node
        result = await session.run(
            "MATCH (m:SyncMetadata {endpoint: $ep}) RETURN m.endpoint AS ep",
            ep=ENDPOINT,
        )
        record = await result.single()
        assert record is not None, "Expected SyncMetadata node for e2e endpoint"
        assert record["ep"] == ENDPOINT

    # ── 4. Assert dashboard responses ────────────────────────────────
    # Point the dashboard's Neo4j env at our local instance
    os.environ["WP6_NEO4J_URI"] = "bolt://localhost:7687"
    os.environ["WP6_NEO4J_USER"] = "neo4j"
    os.environ["WP6_NEO4J_PASSWORD"] = "localdevpassword"

    # Import app after env is set so deps pick up the right connection
    from wp6_data.blue.dashboard import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # /health
        resp = await client.get("/health")
        assert resp.status_code == 200

        # / (home) — should list our e2e devices and sensors
        resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.text
        assert "e2e-device-alpha" in body
        assert "e2e-temperature" in body

        # /chart/e2e-temperature — should render a plotly chart
        resp = await client.get("/chart/e2e-temperature")
        assert resp.status_code == 200
        assert "plotly" in resp.text.lower()

        # /device/e2e-device-alpha — should render without error
        resp = await client.get("/device/e2e-device-alpha")
        assert resp.status_code == 200

        # /status — should contain coverage data for our e2e devices
        resp = await client.get("/status")
        assert resp.status_code == 200
        assert "e2e-device-alpha" in resp.text
