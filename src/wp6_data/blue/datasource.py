"""Blue dashboard data-source dispatcher.

Routes use ``Depends(get_active_source)`` to get a ``(module, name)`` tuple.
The active source is determined by cookie, falling back to the configured default.
"""

from types import ModuleType
from typing import Annotated

from fastapi import Cookie, Depends

from wp6_data.blue import deps, yookr
from wp6_data.config import Settings

SOURCES: dict[str, ModuleType] = {
    "spohf-datalake": deps,
    "yookr": yookr,
}

SOURCE_LABELS: dict[str, str] = {
    "spohf-datalake": "SPoHF Datalake",
    "yookr": "Yookr API",
}

_settings = Settings()


def _resolve_source(cookie_value: str | None) -> tuple[ModuleType, str]:
    """Return (source_module, source_name) from cookie or default."""
    name = cookie_value if cookie_value in SOURCES else _settings.blue_default_source
    return SOURCES[name], name


async def _get_active_source(
    wp6_blue_source: Annotated[str | None, Cookie()] = None,
) -> tuple[ModuleType, str]:
    """FastAPI dependency: resolve the active data source from cookie."""
    return _resolve_source(wp6_blue_source)


GetActiveSource = Depends(_get_active_source)
