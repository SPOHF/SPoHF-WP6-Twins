"""Shared test fixtures for api/, graph/, and sync/ modules."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from wp6_data.api.models import ApiResponse, SensorReading


def make_reading(**overrides) -> SensorReading:
    """Factory for SensorReading with sensible defaults."""
    defaults = {
        "sensor_id": "device-001",
        "project": "test-project",
        "device_name": "Test Device",
        "sensor_tag": "temperature",
        "value": "21.5",
        "datetime_measure": datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        "timestamp": datetime(2024, 6, 15, 12, 0, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SensorReading(**defaults)


def make_api_response(readings: list[SensorReading] | None = None) -> ApiResponse:
    """Factory for ApiResponse wrapping a list of readings."""
    readings = readings or []
    return ApiResponse(results=readings, count=len(readings))


@pytest.fixture()
def mock_neo4j_session():
    """AsyncMock neo4j session with .run() returning .single() -> None."""
    session = AsyncMock()
    result = AsyncMock()
    result.single.return_value = None
    session.run.return_value = result
    return session


@pytest.fixture()
def mock_settings():
    """MagicMock Settings with all sync/neo4j/api fields populated."""
    s = MagicMock()
    s.api_base_url = "https://api.example.com"
    s.api_token = "test-token"
    s.neo4j_uri = "bolt://localhost:7687"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "password"
    s.neo4j_database = "neo4j"
    s.sync_page_size = 100
    s.sync_mode = "incremental"
    s.sync_window_days = 1
    s.endpoint_list = ["yookr-data"]
    return s
