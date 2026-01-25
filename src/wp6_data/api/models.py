"""Pydantic models for SPoHF API responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SensorReading(BaseModel):
    """Single sensor reading from the API.

    Each row represents one measurement value for one sensor tag.
    Multiple tags (soilMoisture, temperature, etc.) come as separate rows.
    """

    sensor_id: str  # UUID of the device
    project: str = "unknown"  # Optional - some records don't have it
    device_name: str = "unknown"  # Optional - some records don't have it
    sensor_tag: str  # Measurement type: solarRadiation, soilMoisture, etc.
    value: str  # Coerced to string
    metadata: dict[str, Any] | None = None
    datetime_measure: datetime  # When measurement was taken
    timestamp: datetime  # When ingested into API

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value_to_string(cls, v: Any) -> str:
        """Coerce value to string - API sometimes returns float."""
        return str(v) if v is not None else ""

    @property
    def value_float(self) -> float | None:
        """Parse value to float, returning None if not parseable."""
        try:
            return float(self.value)
        except (ValueError, TypeError):
            return None


class ApiResponse(BaseModel):
    """Paginated API response wrapper."""

    results: list[SensorReading]
    count: int = Field(description="Number of results in this page")
