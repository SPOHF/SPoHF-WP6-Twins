"""CSV export job for WP6 Red - generates nightly sensor data exports."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import aiomysql
import pandas as pd
import structlog
from dotenv import load_dotenv

from wp6_data.config import RedSettings
from wp6_data.red.db import COMMON_MEASUREMENTS, SENSOR_TABLES

log = structlog.get_logger()


async def export_table(
    pool: aiomysql.Pool,
    table: str,
    output_dir: Path,
) -> Path | None:
    """Export all data from a sensor table to CSV.

    Returns the path to the exported file, or None if no data.
    """
    columns = SENSOR_TABLES[table]
    all_columns = ["device_id", "received_at", *columns, *COMMON_MEASUREMENTS]

    async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
        query = f"""
            SELECT {', '.join(all_columns)}
            FROM {table}
            ORDER BY received_at ASC
        """
        await cursor.execute(query)
        rows = await cursor.fetchall()

    if not rows:
        log.info("no_data", table=table)
        return None

    df = pd.DataFrame(rows)
    output_path = output_dir / f"{table}.csv"
    df.to_csv(output_path, index=False)

    log.info("exported", table=table, rows=len(df), path=str(output_path))
    return output_path


async def run_export() -> None:
    """Run the full CSV export job."""
    settings = RedSettings()
    export_dir = Path(settings.export_dir)
    log.info("export_started", export_dir=str(export_dir))

    # Ensure export directory exists
    export_dir.mkdir(parents=True, exist_ok=True)

    # Connect to MySQL
    db_host = settings.db_host
    db_port = settings.db_port
    db_name = settings.db_name
    db_user = settings.db_user
    db_password = settings.db_password

    pool = await aiomysql.create_pool(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        db=db_name,
        autocommit=True,
    )

    try:
        exported = {}
        for table in SENSOR_TABLES:
            try:
                path = await export_table(pool, table, export_dir)
                if path:
                    exported[table] = datetime.now(UTC).isoformat()
            except Exception as e:
                log.error("export_failed", table=table, error=str(e))

        # Write metadata file with export timestamps per table
        metadata = {
            "exported_at": datetime.now(UTC).isoformat(),
            "tables": exported,
        }
        metadata_path = export_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        log.info("export_completed", tables=list(exported.keys()))

    finally:
        pool.close()
        await pool.wait_closed()


def main() -> None:
    """Entry point for the export CLI."""
    load_dotenv()
    asyncio.run(run_export())


if __name__ == "__main__":
    main()
