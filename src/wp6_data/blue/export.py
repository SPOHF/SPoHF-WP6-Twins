"""CSV export job for WP6 Blue - generates nightly sensor data exports."""

import asyncio
from datetime import UTC, datetime

import pandas as pd
import structlog
from dotenv import load_dotenv

from wp6_data.blue import deps
from wp6_data.blue.tsdb import ensure_schema_blue
from wp6_data.config import Settings
from wp6_data.db import close_pool, get_pool, init_pool
from wp6_data.shared.blob import BlobStore
from wp6_data.shared.export import (
    clear_exports,
    csv_key,
    sanitise_name,
    write_export_metadata,
)

log = structlog.get_logger()


async def export_device(device_name: str, store: BlobStore) -> str | None:
    """Export all readings for a device to a wide-format CSV.

    Pivots sensor_tags into columns so each row is a timestamp.
    Returns the key the CSV was written to, or None if no data.
    """
    pool = get_pool()

    query = """
        SELECT time, sensor_tag, value
        FROM readings
        WHERE device_name = %(device)s
        ORDER BY time
    """

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(query, {"device": device_name})
        rows = await cur.fetchall()

    if not rows:
        log.info("no_data", device=device_name)
        return None

    df = pd.DataFrame(rows, columns=["time", "sensor_tag", "value"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Pivot to wide format: one column per sensor_tag
    wide = df.pivot_table(index="time", columns="sensor_tag", values="value", aggfunc="first")
    wide = wide.sort_index()
    wide.columns.name = None  # Remove "sensor_tag" header label

    # Blue device names carry "/" and spaces, which would become accidental
    # key hierarchy in the bucket.
    key = csv_key(sanitise_name(device_name))
    await store.put(key, wide.to_csv().encode("utf-8"), content_type="text/csv")

    log.info("exported", device=device_name, rows=len(wide), key=key)
    return key


async def get_device_names() -> list[str]:
    """Get all distinct device names from the readings table."""
    pool = get_pool()

    query = """
        SELECT DISTINCT device_name
        FROM readings
        ORDER BY device_name
    """

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(query)
        rows = await cur.fetchall()

    return [row[0] for row in rows]


async def run_export() -> None:
    """Run the full CSV export job."""
    settings = Settings()
    store = deps.EXPORT_STORE
    log.info("export_started", store=type(store).__name__)

    removed = await clear_exports(store)
    if removed:
        log.info("cleared_stale_exports", files_removed=removed)

    # Initialise DB pool
    await init_pool(settings.tsdb_url)
    pool = get_pool()
    await ensure_schema_blue(pool)

    try:
        devices = await get_device_names()
        log.info("found_devices", count=len(devices))

        exported = {}
        for device in devices:
            try:
                key = await export_device(device, store)
                if key:
                    exported[device] = datetime.now(UTC).isoformat()
            except Exception as e:
                log.error("export_failed", device=device, error=str(e))

        # Record export timestamps per device, beside the CSVs
        await write_export_metadata(
            store,
            {
                "exported_at": datetime.now(UTC).isoformat(),
                "devices": exported,
            },
        )

        log.info("export_completed", devices=list(exported.keys()))

    finally:
        await close_pool()


def main() -> None:
    """Entry point for the export CLI."""
    from opentelemetry import trace

    from wp6_data.shared.observability import setup_observability

    load_dotenv()
    setup_observability("wp6-blue-export")
    with trace.get_tracer(__name__).start_as_current_span("blue.export"):
        asyncio.run(run_export())


if __name__ == "__main__":
    main()
