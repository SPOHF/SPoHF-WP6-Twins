"""Shared FastAPI dependencies for extracting twin config from app state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from wp6_data.shared.metadata import MetadataRegistry
    from wp6_data.shared.twin import SensorDataProvider, TwinConfig


def get_twin_config(request: Request) -> TwinConfig:
    """Extract TwinConfig from app.state (set by the app factory)."""
    return request.app.state.twin_config


def get_provider(request: Request) -> SensorDataProvider:
    """Extract the active SensorDataProvider.

    This default is overridden by the app factory with a cookie-based
    dispatcher for multi-source twins.
    """
    return request.app.state.twin_config.default_provider


def get_metadata(request: Request) -> MetadataRegistry:
    """Extract the MetadataRegistry."""
    return request.app.state.twin_config.metadata
