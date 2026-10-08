"""Which multi-height wires are installed.

Upstream's ``wire_sensor_map`` is the source of truth: it maps every Modbus
sensor to the wire and position it is physically installed on, and a wire with
no active sensor is not installed. Every view, the risk CLI and the export job
enumerate from here, so a wire the map retires disappears platform-wide — even
though ``wire_sensors`` keeps carrying rows for it (see
``docs/red/wire-data-coverage.md`` for the July–October 2026 remap).

Which heights and measurements a wire *reports* is not declared anywhere: the
table's columns are fixed, and a column a wire never fills simply has no
readings yet.

Lives above `multi_height` and `risk` because both need it and `multi_height`
already depends on `risk.metrics` — a shared home avoids inverting that.
"""

from cachetools import TTLCache

from wp6_data.red import deps
from wp6_data.red.db import (
    WIRE_DEVICE_HEIGHTS,
    MySQLConnection,
    wire_device_id,
    wire_height_measurements,
)

# The map changes only when sensors are re-installed, but picking that up must
# not need a restart — and it is read on every wire request, from a remote DB.
_wire_ids_cache: TTLCache[str, list[str]] = TTLCache(maxsize=1, ttl=300)
_CACHE_KEY = "red:wire-ids"


def invalidate_wire_cache() -> None:
    """Forget the cached wire list, so the next read goes to the map."""
    _wire_ids_cache.clear()


async def wire_ids(db: MySQLConnection | None = None) -> list[str]:
    """Physical ids of the installed wires, sorted."""
    if _CACHE_KEY in _wire_ids_cache:
        return _wire_ids_cache[_CACHE_KEY]
    db = db or deps.db
    if db is None:
        raise RuntimeError("Database not connected")
    ids = await db.get_active_wire_ids()
    _wire_ids_cache[_CACHE_KEY] = ids
    return ids


async def wire_devices(db: MySQLConnection | None = None) -> dict[str, list[str]]:
    """Virtual per-height device id -> its sensors, for every installed wire."""
    return {
        wire_device_id(wire, height): wire_height_measurements(height)
        for wire in await wire_ids(db)
        for height in WIRE_DEVICE_HEIGHTS
    }
