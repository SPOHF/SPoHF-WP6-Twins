"""One-off script: train soil forecast models and write them to a local directory.

The dashboard does not use this — it fits on demand and stores the models in the
object store (`blue/models/`). This writes .pkl files plus a manifest.csv for
someone inspecting a fit by hand.

Untested since the API drifted under it: `BlueSensorProvider(project=...)` went
away with the `project` column, and `settings.blue_export_dir` went away when
exports moved to the object store. Both are repaired below, but nothing exercises
this path, so treat a run as exploratory.
"""
import asyncio
import selectors
from datetime import UTC, datetime
from pathlib import Path

from wp6_data.blue.routes.monitor._treatment import load_device_treatment_map

from wp6_data.blue.deps import close_db, init_db
from wp6_data.blue.provider import BlueSensorProvider
from wp6_data.blue.soil_forecaster import train_all_forecasters
from wp6_data.config import Settings

settings = Settings()


async def main() -> None:
    await init_db(settings.tsdb_url)

    provider = BlueSensorProvider()
    print("Fetching 2025 soil data from TimescaleDB…")
    df = await provider.fetch_data(
        sensor_tags=["soilMoisture", "soilTemperature"],
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
    )

    await close_db()

    if df.empty:
        print("No data returned — check DB connection and source key.")
        return

    print(f"Fetched {len(df):,} rows.")

    treatment_map = load_device_treatment_map()
    df["treatment"] = df["device"].map(treatment_map)
    df = df.dropna(subset=["treatment"])
    print(f"After treatment mapping: {len(df):,} rows, "
          f"{df['treatment'].nunique()} treatments.")

    train_df = df.rename(columns={"time": "timestamp", "sensor": "sensor_type"})

    # An explicit local directory: the dashboard's models live in the object
    # store now, and this script deliberately does not write there.
    output_dir = Path("exports-blue") / "models"
    print(f"Output directory: {output_dir}")

    train_all_forecasters(train_df, output_dir=str(output_dir))


asyncio.run(main(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
