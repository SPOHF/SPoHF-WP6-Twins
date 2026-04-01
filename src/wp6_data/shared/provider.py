"""Sensor data provider protocol and twin configuration.

Defines the contract that every digital twin's data layer must satisfy,
plus the TwinConfig dataclass that drives the app factory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from fastapi import APIRouter

    from wp6_data.shared.metadata import MetadataRegistry


@runtime_checkable
class SensorDataProvider(Protocol):
    """Minimal interface every twin's data layer must satisfy.

    Shared routes depend only on these three methods.
    Twin-specific methods (e.g. red's get_par_readings) live on the
    concrete implementations and are accessed by twin-specific routes.
    """

    async def fetch_data(
        self,
        sensor_tags: list[str] | None = None,
        device_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500_000,
    ) -> pd.DataFrame:
        """Fetch time-series readings.

        Returns DataFrame with columns: device, sensor, time, value.
        """
        ...

    async def fetch_available_sensors(self) -> list[dict[str, Any]]:
        """List available sensors with reading counts.

        Returns [{device, sensor, readings, ...}, ...].
        """
        ...

    async def fetch_device_data(self) -> dict[str, dict]:
        """Device overview for the home page.

        Returns {device_id: {sensors: [str, ...], readings: int}}.
        """
        ...

    @property
    def data_source_label(self) -> str | None:
        """Optional display label for multi-source twins (e.g. blue's source switcher).

        Returns None if the twin has a single source.
        """
        ...


@dataclass
class TwinConfig:
    """Everything needed to create a twin dashboard app."""

    twin_id: str
    title: str
    provider: SensorDataProvider
    metadata: MetadataRegistry
    export_dir: Path
    extra_routers: list[APIRouter] = field(default_factory=list)
    hero_cards: list[Callable[..., Awaitable[str] | str]] = field(
        default_factory=list,
    )
    provider_dependency: Callable[..., Any] | None = None
    home_extra_html: str = ""
    export_sanitise_names: bool = False
    lifespan_startup: Callable[..., Awaitable[None]] | None = None
    lifespan_shutdown: Callable[..., Awaitable[None]] | None = None
