"""CSV export job for WP6 Red - generates nightly per-device sensor data exports.

Also serves as the daily TSDB maintenance touchpoint: refreshes the
`sensors_daily_summary` continuous aggregate and writes a `red-export` row
to `sync_metadata` so the status page reflects nightly job health.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import structlog
from dotenv import load_dotenv

from wp6_data.config import RedSettings
from wp6_data.db.pool import close_pool, get_pool, init_pool
from wp6_data.db.queries import record_sync_run, refresh_sensor_summary
from wp6_data.red.db import COMMON_MEASUREMENTS, SENSOR_TABLES, MySQLConnection
from wp6_data.red.tsdb import ensure_schema_red
from wp6_data.shared.export import clear_export_dir

log = structlog.get_logger()


async def export_device(
    db: MySQLConnection,
    device_id: str,
    tables: list[str],
    output_dir: Path,
) -> Path | None:
    """Export all data for a device across its tables to CSV.

    Returns the path to the exported file, or None if no data.
    """
    all_frames = []

    for table in tables:
        columns = SENSOR_TABLES[table]
        all_columns = ["received_at", *columns, *COMMON_MEASUREMENTS]

        async with db.pool.acquire() as conn, conn.cursor() as cursor:
            query = f"""
                SELECT {', '.join(all_columns)}
                FROM {table}
                WHERE device_id = %s
                ORDER BY received_at ASC
            """
            await cursor.execute(query, (device_id,))
            rows = await cursor.fetchall()

        if rows:
            all_frames.append(pd.DataFrame(rows, columns=all_columns))

    if not all_frames:
        log.info("no_data", device=device_id)
        return None

    df = pd.concat(all_frames, ignore_index=True).sort_values("received_at")
    output_path = output_dir / f"{device_id}.csv"
    df.to_csv(output_path, index=False)

    log.info("exported", device=device_id, rows=len(df), path=str(output_path))
    return output_path


async def run_export() -> None:
    """Run the full CSV export job and refresh TSDB-side daily aggregates."""
    settings = RedSettings()
    export_dir = Path(settings.export_dir)
    log.info("export_started", export_dir=str(export_dir))

    export_dir.mkdir(parents=True, exist_ok=True)
    removed = clear_export_dir(export_dir)
    if removed:
        log.info("cleared_stale_exports", files_removed=removed)

    started = time.monotonic()
    db = MySQLConnection(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
    )
    await db.connect()

    exported: dict[str, str] = {}
    try:
        all_devices = await db.get_all_devices()
        log.info("found_devices", count=len(all_devices))

        for device_id, info in all_devices.items():
            try:
                path = await export_device(db, device_id, info["tables"], export_dir)
                if path:
                    exported[device_id] = datetime.now(UTC).isoformat()
            except Exception as e:
                log.error("export_failed", device=device_id, error=str(e))

        metadata = {
            "exported_at": datetime.now(UTC).isoformat(),
            "devices": exported,
        }
        metadata_path = export_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        log.info("export_completed", devices=list(exported.keys()))

    finally:
        await db.close()

    await _refresh_red_tsdb(settings.tsdb_url, len(exported), started)


async def _refresh_red_tsdb(tsdb_url: str, records: int, started: float) -> None:
    """Refresh the cagg and record a `red-export` sync_metadata row.

    Failures here must not crash the export job — the CSV files are already
    written to the PVC and serve the dashboard's download links regardless.
    """
    try:
        await init_pool(tsdb_url)
        pool = get_pool()
        await ensure_schema_red(pool)
        await refresh_sensor_summary(pool)
        duration_sec = time.monotonic() - started
        async with pool.connection() as conn:
            await record_sync_run(
                conn,
                "red-export",
                success=True,
                duration_sec=duration_sec,
                records=records,
                last_timestamp=datetime.now(UTC),
            )
            await conn.commit()
    except Exception as e:
        log.exception("red_tsdb_refresh_failed")
        try:
            duration_sec = time.monotonic() - started
            async with get_pool().connection() as conn:
                await record_sync_run(
                    conn,
                    "red-export",
                    success=False,
                    duration_sec=duration_sec,
                    records=records,
                    error=str(e),
                )
                await conn.commit()
        except Exception:
            log.exception("red_tsdb_refresh_audit_failed")
    finally:
        try:
            await close_pool()
        except Exception:
            log.exception("red_tsdb_pool_close_failed")


def main() -> None:
    """Entry point for the export CLI."""
    load_dotenv()
    asyncio.run(run_export())


if __name__ == "__main__":
    main()
