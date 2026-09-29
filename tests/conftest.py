"""Shared test fixtures for api/, db/, and sync/ modules."""

import os

# Pydantic Settings validation runs at import time; ensure required envs
# exist before any test module imports red.deps / RedSettings.
os.environ.setdefault(
    "WP6_RED_TSDB_URL", "postgresql://wp6_red:wp6dev@localhost:5433/wp6_red",
)

# Object storage is mandatory (wp6_data.shared.blob.make_store refuses to build
# without it), and red/blue deps construct their export store at import. A
# boto3 client does not connect when it is created, so these values only have
# to exist -- nothing here reaches the network. Unit tests that actually
# exercise a store inject LocalBlobStore explicitly; the ones that talk to a
# real MinIO live in tests/e2e.
#
# Deliberately an endpoint nothing listens on: if a unit test ever does try to
# reach the store, it should fail loudly rather than quietly hit whatever the
# developer happens to be running.
os.environ.setdefault("WP6_S3_BUCKET", "unit-tests-should-not-reach-this")
os.environ.setdefault("WP6_S3_ENDPOINT_URL", "http://127.0.0.1:9")
os.environ.setdefault("WP6_S3_ACCESS_KEY_ID", "unit")
os.environ.setdefault("WP6_S3_SECRET_ACCESS_KEY", "unit-secret")

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from wp6_data.api.models import ApiResponse, SensorReading
from wp6_data.config import Settings


def make_reading(**overrides) -> SensorReading:
    """Factory for SensorReading with sensible defaults."""
    defaults = {
        "sensor_id": "device-001",
        "device_name": "Test Device",
        "sensor_tag": "temperature",
        "value": "21.5",
        "datetime_measure": datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SensorReading(**defaults)


def make_api_response(readings: list[SensorReading] | None = None) -> ApiResponse:
    """Factory for ApiResponse wrapping a list of readings."""
    readings = readings or []
    return ApiResponse(results=readings, count=len(readings))


@pytest.fixture()
def mock_db_conn():
    """AsyncMock psycopg connection with cursor context manager."""
    conn = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=None)
    cursor.fetchall = AsyncMock(return_value=[])
    cursor.statusmessage = "INSERT 0 1"

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=cursor)
    ctx.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=ctx)

    return conn


@pytest.fixture()
def mock_settings():
    """MagicMock Settings with all sync/db/api fields populated."""
    s = MagicMock()
    s.api_base_url = "https://api.example.com"
    s.api_token = "test-token"
    s.tsdb_url = "postgresql://wp6:wp6dev@localhost:5432/wp6_blue"
    s.sync_page_size = 100
    s.sync_mode = "incremental"
    s.sync_window_days = 1
    s.sync_start = Settings.model_fields["sync_start"].default
    s.sync_end = Settings.model_fields["sync_end"].default
    s.endpoint_list = ["yookr-data"]
    return s
