"""E2E: Blue incremental sync → TimescaleDB → dashboard renders the data."""

import os
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
import respx
from httpx import ASGITransport
from psycopg.rows import dict_row

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

TSDB_DSN = "postgresql://wp6:wp6dev@localhost:5433/wp6_blue"


def _make_settings() -> Settings:
    """Build a real Settings object pointed at localhost TimescaleDB + fake API."""
    return Settings(
        api_base_url=FAKE_API_URL,
        api_token="e2e-dummy-token",
        tsdb_url=TSDB_DSN,
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
async def test_incremental_sync_and_dashboard_display(tsdb_conn):
    """Full pipeline: mock API → sync → TimescaleDB state → dashboard HTTP."""

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

    # ── 3. Assert TimescaleDB state ──────────────────────────────────
    async with (
        await psycopg.AsyncConnection.connect(TSDB_DSN) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        # Device names in readings
        await cur.execute(
            "SELECT DISTINCT device_name FROM readings "
            "WHERE device_name LIKE 'e2e-%' ORDER BY device_name"
        )
        devices = [r["device_name"] for r in await cur.fetchall()]
        assert "e2e-device-alpha" in devices
        assert "e2e-device-beta" in devices

        # Sensor tags
        await cur.execute(
            "SELECT DISTINCT sensor_tag FROM readings "
            "WHERE sensor_tag LIKE 'e2e-%' ORDER BY sensor_tag"
        )
        tags = [r["sensor_tag"] for r in await cur.fetchall()]
        assert "e2e-temperature" in tags
        assert "e2e-humidity" in tags

        # Reading values
        await cur.execute(
            "SELECT raw_value FROM readings "
            "WHERE sensor_tag = 'e2e-temperature'"
        )
        values = [r["raw_value"] for r in await cur.fetchall()]
        assert "21.5" in values

        # Daily coverage entries
        await cur.execute(
            "SELECT count(*) AS cnt FROM daily_coverage "
            "WHERE device_name LIKE 'e2e-%'"
        )
        row = await cur.fetchone()
        assert row["cnt"] > 0, "Expected daily_coverage entries"

        # Sync metadata
        await cur.execute(
            "SELECT endpoint FROM sync_metadata WHERE endpoint = %(ep)s",
            {"ep": ENDPOINT},
        )
        row = await cur.fetchone()
        assert row is not None, "Expected sync_metadata row for e2e endpoint"
        assert row["endpoint"] == ENDPOINT

    # ── 4. Assert dashboard responses ────────────────────────────────
    os.environ["WP6_TSDB_URL"] = TSDB_DSN

    # Import app after env is set so deps pick up the right connection
    from wp6_data.blue.dashboard import app

    transport = ASGITransport(app=app)
    # ASGITransport does not drive FastAPI lifespan, so init_pool() never runs
    # unless we enter the lifespan context manually.
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=True,
    ) as client:
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
