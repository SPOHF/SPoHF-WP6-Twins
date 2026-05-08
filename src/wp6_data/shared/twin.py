"""Twin abstraction layer: data provider protocol, theme, and configuration.

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

    Shared routes depend only on these methods.
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

        Returns ``{device_id: {sensors: [str, ...], readings: int,
                              last_seen: datetime | None}}``.
        """
        ...

    async def fetch_manual_metadata(self) -> dict[str, Any]:
        """Aggregate metadata for manually-uploaded measurements.

        Returns ``{"uploads": {source: datetime},
                  "measurements": {sensor_key: datetime}}``.
        Empty dicts when the twin has no manual data.
        """
        ...

    async def fetch_sync_metrics(self) -> list[dict[str, Any]]:
        """Sync run metadata for the status page.

        Returns [{endpoint, last_run_at, last_run_success, ...}].
        Empty list if the twin has no sync mechanism.
        """
        ...

    async def fetch_daily_coverage(self) -> list[dict[str, Any]]:
        """Daily data coverage for the status page timeline.

        Returns [{device, sensor, day}, ...].
        Empty list if coverage tracking is not available.
        """
        ...

    @property
    def data_source_label(self) -> str | None:
        """The active data source key, used by templates for the source toggle.

        Returns the DataSource.key this provider belongs to, or None
        if the twin has only one source (no toggle rendered).
        """
        ...


@dataclass
class ThemeColors:
    """Colour palette for a twin's dashboard.

    Used to generate CSS custom properties at startup.
    ``surface_rgb`` is the comma-separated RGB triple used in rgba() values.
    """

    primary: str
    primary_light: str
    primary_dark: str
    accent: str
    surface_rgb: str  # e.g. "37, 99, 235"


@dataclass
class DataSource:
    """A named data source with its provider.

    When a twin has multiple data sources, the platform renders a
    navigation toggle and manages the cookie-based switching.
    The provider on each DataSource handles the actual data access.
    """

    key: str                      # cookie value, e.g. "spohf-datalake"
    label: str                    # display name in toggle
    provider: SensorDataProvider  # data access for this source


@dataclass
class TwinConfig:
    """Everything needed to create a twin dashboard app."""

    twin_id: str
    title: str
    data_sources: list[DataSource]
    metadata: MetadataRegistry
    export_dir: Path
    theme: ThemeColors
    extra_routers: list[APIRouter] = field(default_factory=list)
    hero_cards: list[Callable[..., Awaitable[str] | str]] = field(
        default_factory=list,
    )
    status_extras: list[Callable[..., Awaitable[str] | str]] = field(
        default_factory=list,
    )
    home_extra_html: str = ""
    require_auth: bool = True
    export_sanitise_names: bool = False
    lifespan_startup: Callable[..., Awaitable[None]] | None = None
    lifespan_shutdown: Callable[..., Awaitable[None]] | None = None

    @property
    def default_provider(self) -> SensorDataProvider:
        """The first data source's provider (used as default)."""
        return self.data_sources[0].provider
