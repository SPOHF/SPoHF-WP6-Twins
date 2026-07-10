"""Which multi-height wires exist, and whether the data agrees.

`metadata.yaml` is the source of truth for the installed wires (red ADR 0001:
"enumeration is metadata-driven, so a new wire means new `type: "wire"` entries,
not new code"). Every view, the risk CLI and the export job enumerate from here,
so a wire the greenhouse reports but nobody declared is invisible platform-wide.
:func:`undeclared_wire_ids` is what notices.

Lives above `multi_height` and `risk` because both need it and `multi_height`
already depends on `risk.metrics` — a shared home avoids inverting that.
"""

from wp6_data.red import deps
from wp6_data.red.db import MySQLConnection, wire_physical_id


def wire_ids() -> list[str]:
    """Physical wire ids declared in metadata (devices typed 'wire'), sorted."""
    ids = {
        wire_physical_id(device_id)
        for device_id, meta in deps.metadata.devices.items()
        if meta.type == "wire"
    }
    return sorted(ids)


async def undeclared_wire_ids(db: MySQLConnection) -> list[str]:
    """Physical wires reporting into wire_sensors but absent from metadata, sorted.

    One-directional on purpose: a declared wire that has gone silent is a dead
    sensor (the coverage status page's job), whereas a reporting wire nobody
    declared is a config gap here — and one that silently drops its data.
    """
    summary = await db.get_wire_device_summary()
    reporting = {wire_physical_id(device_id) for device_id in summary}
    return sorted(reporting - set(wire_ids()))
