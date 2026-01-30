# !/usr/bin/env python3

"""Demonstrate SPoHF API pagination behavior.

Shows that paginating with increasing 'from' offsets does not return all data,
and tracks duplicate records returned by the API.
Requires WP6_API_TOKEN env var (or .env file).
TODO: remove when API is fixed.
"""

import asyncio
import os
from collections import defaultdict
from datetime import UTC, datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("WP6_API_BASE_URL", "https://backoffice.spohf.com").rstrip("/")
TOKEN = os.environ["WP6_API_TOKEN"]
ENDPOINT = "yookr-data"
PAGE_SIZE = 1000
TIMESTAMP = datetime(2024, 1, 1, tzinfo=UTC)


async def main():
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    # per sensor_tag: count, min date, max date, duplicates
    stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "duplicates": 0, "min": None, "max": None}
    )
    # Track seen records: (sensor_id, sensor_tag, datetime_measure) -> seen count
    seen: dict[tuple, int] = defaultdict(int)

    offset = 0
    total = 0
    total_duplicates = 0

    async with httpx.AsyncClient() as client:
        while True:
            url = f"{BASE_URL}/api/v1/data/{ENDPOINT}"
            params = {
                "timestamp": TIMESTAMP.isoformat(),
                "size": str(PAGE_SIZE),
                "from": str(offset),
            }

            print(f"Fetching offset={offset} ...", end=" ", flush=True)
            resp = await client.get(url, params=params, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            count = data.get("count", len(results))
            print(f"got {count} records")

            if not results:
                break

            for r in results:
                tag = r.get("sensor_tag", "?")
                sid = r.get("sensor_id", "?")
                dt = r.get("datetime_measure", "")
                val = r.get("value", "")

                key = (sid, tag, dt, val)
                seen[key] += 1

                s = stats[tag]
                if seen[key] > 1:
                    s["duplicates"] += 1
                    total_duplicates += 1
                else:
                    s["count"] += 1

                if dt:
                    if s["min"] is None or dt < s["min"]:
                        s["min"] = dt
                    if s["max"] is None or dt > s["max"]:
                        s["max"] = dt

            total += len(results)

            if count < PAGE_SIZE:
                break

            offset += PAGE_SIZE

    # Print summary table
    print(f"\nTotal records fetched: {total}")
    print(f"Total unique: {total - total_duplicates}")
    print(f"Total duplicates: {total_duplicates}")
    print()
    print(
        f"{'Sensor Tag':<30} {'Unique':>8} {'Dupes':>8}"
        f"  {'Min Date':<25} {'Max Date':<25}"
    )
    print("-" * 110)
    for tag in sorted(stats):
        s = stats[tag]
        print(
            f"{tag:<30} {s['count']:>8} {s['duplicates']:>8}"
            f"  {s['min'] or '':<25} {s['max'] or '':<25}"
        )


if __name__ == "__main__":
    asyncio.run(main())
