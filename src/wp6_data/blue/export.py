"""CSV export job for WP6 Blue - generates nightly sensor data exports."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import structlog
from dotenv import load_dotenv

from wp6_data.config import Settings
from wp6_data.db import close_pool, get_pool, init_pool
from wp6_data.db.schema import ensure_schema
from wp6_data.shared.export import clear_export_dir

log = structlog.get_logger()


async def export_device(
    device_name: str,
    output_dir: Path,
    project_exclude: str = "yookr-direct",
) -> Path | None:
    """Export all readings for a device to a wide-format CSV.

    Pivots sensor_tags into columns so each row is a timestamp.
    Returns the path to the exported file, or None if no data.
    """
    pool = get_pool()

    query = """
        SELECT time, sensor_tag, value
        FROM readings
        WHERE device_name = %(device)s
          AND project != %(excluded_project)s
        ORDER BY time
    """

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(query, {"device": device_name, "excluded_project": project_exclude})
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

    # Sanitise device name for filename
    safe_name = device_name.replace("/", "_").replace(" ", "_")
    output_path = output_dir / f"{safe_name}.csv"
    wide.to_csv(output_path)

    log.info("exported", device=device_name, rows=len(wide), path=str(output_path))
    return output_path


async def get_device_names(project_exclude: str = "yookr-direct") -> list[str]:
    """Get all distinct device names from the readings table."""
    pool = get_pool()

    query = """
        SELECT DISTINCT device_name
        FROM readings
        WHERE project != %(excluded_project)s
        ORDER BY device_name
    """

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(query, {"excluded_project": project_exclude})
        rows = await cur.fetchall()

    return [row[0] for row in rows]


async def run_export() -> None:
    """Run the full CSV export job."""
    settings = Settings()
    export_dir = Path(settings.blue_export_dir)
    log.info("export_started", export_dir=str(export_dir))

    export_dir.mkdir(parents=True, exist_ok=True)
    removed = clear_export_dir(export_dir)
    if removed:
        log.info("cleared_stale_exports", files_removed=removed)

    # Initialise DB pool
    await init_pool(settings.tsdb_url)
    pool = get_pool()
    await ensure_schema(pool)

    try:
        devices = await get_device_names()
        log.info("found_devices", count=len(devices))

        exported = {}
        for device in devices:
            try:
                path = await export_device(device, export_dir)
                if path:
                    exported[device] = datetime.now(UTC).isoformat()
            except Exception as e:
                log.error("export_failed", device=device, error=str(e))

        # Write metadata file with export timestamps per device
        metadata = {
            "exported_at": datetime.now(UTC).isoformat(),
            "devices": exported,
        }
        metadata_path = export_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        log.info("export_completed", devices=list(exported.keys()))

    finally:
        await close_pool()


def main() -> None:
    """Entry point for the export CLI."""
    load_dotenv()
    asyncio.run(run_export())


if __name__ == "__main__":
    main()
