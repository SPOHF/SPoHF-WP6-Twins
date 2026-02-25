#!/usr/bin/env python3
"""Check which devices report a given sensor tag in the SPoHF API.

Requirements:
    pip install httpx

Usage:
    python api_check_sensors.py --token YOUR_API_TOKEN
    python api_check_sensors.py --token YOUR_API_TOKEN --tag temperature --days 30

Options:
    --token   API bearer token (required)
    --url     API base URL (default: https://backoffice.spohf.com)
    --tag     Sensor tag to look for (default: soilConductivity)
    --days    Lookback days (default: 7)
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

try:
    import httpx
except ImportError:
    print("Missing dependency. Install with: pip install httpx")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Check sensor availability in SPoHF API")
    parser.add_argument("--token", required=True, help="API bearer token")
    parser.add_argument("--url", default="https://backoffice.spohf.com", help="API base URL")
    parser.add_argument("--tag", default="soilConductivity", help="Sensor tag to look for")
    parser.add_argument("--days", type=int, default=7, help="Lookback days")
    args = parser.parse_args()

    client = httpx.Client(
        headers={"Authorization": f"Bearer {args.token}"},
        follow_redirects=True,
    )

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    url = f"{args.url.rstrip('/')}/api/v1/data/yookr-data"

    offset = 0
    devices: dict[str, int] = {}
    all_tags: dict[str, int] = {}
    total = 0

    print(f"Querying {url}")
    print(f"  from: {start.isoformat()}")
    print(f"  to:   {end.isoformat()}")

    while True:
        resp = client.get(url, params={
            "timestamp_from": start.isoformat(),
            "timestamp_until": end.isoformat(),
            "size": "1000",
            "from": str(offset),
        })
        if resp.status_code in (301, 302, 401, 403) or "/login" in str(resp.url):
            print(f"\nAuth failed (HTTP {resp.status_code}, url: {resp.url})")
            print("Check that your --token is valid.")
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        total += len(results)
        for rec in results:
            tag = rec.get("sensor_tag", "?")
            all_tags[tag] = all_tags.get(tag, 0) + 1
            if tag == args.tag:
                name = rec.get("device_name", "?")
                devices[name] = devices.get(name, 0) + 1

        if data.get("count", 0) < 1000:
            break
        offset += 1000
        print(f"  fetched {total} records...", flush=True)

    print(f"\nAPI results for past {args.days} days ({total} total records):\n")
    print("All sensor tags:")
    for tag, count in sorted(all_tags.items(), key=lambda x: -x[1]):
        marker = " <--" if tag == args.tag else ""
        print(f"  {tag}: {count}{marker}")

    print(f"\n'{args.tag}' devices: {len(devices)}")
    for name, count in sorted(devices.items()):
        print(f"  {name}: {count} readings")

    if not devices:
        print("  (none found)")


if __name__ == "__main__":
    main()
