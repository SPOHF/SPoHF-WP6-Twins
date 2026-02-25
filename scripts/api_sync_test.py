#!/usr/bin/env python3

"""Validate new SPoHF API timestamp_from/timestamp_to contract.

Tests both full-sync (day-by-day from 2024-01-01) and cron-sync (recent lookback
with duplicate-based early stop) scenarios using the new API parameters.
Requires WP6_API_TOKEN env var (or .env file).
"""

import argparse
import asyncio
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("WP6_API_BASE_URL", "https://backoffice.spohf.com").rstrip("/")
TOKEN = os.environ["WP6_API_TOKEN"]
ENDPOINT = "yookr-data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate SPoHF API sync scenarios")
    parser.add_argument(
        "--mode",
        choices=["full", "cron"],
        default="full",
        help="Sync mode: full (all history) or cron (recent with dupe stop)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=1,
        help="Days per time window (default: 1)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="Records per API page (default: 1000)",
    )
    parser.add_argument(
        "--max-dupes",
        type=int,
        default=100,
        help="Consecutive duplicate records to trigger cron stop (default: 100)",
    )
    parser.add_argument(
        "--cron-lookback-days",
        type=int,
        default=7,
        help="Days to look back in cron mode (default: 7)",
    )
    return parser.parse_args()


async def fetch_page(
    client: httpx.AsyncClient,
    timestamp_from: datetime,
    timestamp_to: datetime,
    offset: int,
    page_size: int,
    max_retries: int = 3,
) -> dict:
    """Fetch a single API page with timestamp_from/timestamp_until, with retry."""
    url = f"{BASE_URL}/api/v1/data/{ENDPOINT}"
    params = {
        "timestamp_from": timestamp_from.isoformat(),
        "timestamp_until": timestamp_to.isoformat(),
        "size": str(page_size),
        "from": str(offset),
    }
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

    for attempt in range(1, max_retries + 1):
        resp = await client.get(url, params=params, headers=headers, timeout=30.0)
        if resp.status_code < 500:
            resp.raise_for_status()
            return resp.json()
        if attempt < max_retries:
            wait = 2**attempt
            print(f"    retry {attempt}/{max_retries} after {resp.status_code}, wait {wait}s")
            await asyncio.sleep(wait)
    resp.raise_for_status()
    return resp.json()  # unreachable, but keeps type checker happy


async def fetch_window(
    client: httpx.AsyncClient,
    timestamp_from: datetime,
    timestamp_to: datetime,
    page_size: int,
    seen: dict[tuple, int],
    stats: dict[str, dict],
) -> tuple[int, int, int]:
    """Paginate all pages within one time window.

    Returns (fetched, new_unique, duplicates) for this window.
    """
    offset = 0
    window_fetched = 0
    window_new = 0
    window_dupes = 0

    while True:
        data = await fetch_page(client, timestamp_from, timestamp_to, offset, page_size)
        results = data.get("results", [])
        count = data.get("count", len(results))

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
                window_dupes += 1
            else:
                s["count"] += 1
                window_new += 1

            if dt:
                if s["min"] is None or dt < s["min"]:
                    s["min"] = dt
                if s["max"] is None or dt > s["max"]:
                    s["max"] = dt

        window_fetched += len(results)

        if count < page_size:
            break
        offset += page_size

    return window_fetched, window_new, window_dupes


async def run_full_sync(
    client: httpx.AsyncClient,
    window_days: int,
    page_size: int,
    seen: dict[tuple, int],
    stats: dict[str, dict],
) -> tuple[int, int, int]:
    """Day-by-day windows from now back to 2024-01-01 (newest first)."""
    oldest = datetime(2024, 1, 1, tzinfo=UTC)
    current_end = datetime.now(UTC) + timedelta(days=1)
    total_days = (current_end - oldest).days
    num_windows = (total_days + window_days - 1) // window_days

    total_fetched = 0
    total_new = 0
    total_dupes = 0
    window_num = 0

    print(f"  {num_windows} windows to process ({total_days} days)\n")

    while current_end > oldest:
        window_start = max(current_end - timedelta(days=window_days), oldest)
        window_num += 1

        fetched, new, dupes = await fetch_window(
            client, window_start, current_end, page_size, seen, stats
        )

        total_fetched += fetched
        total_new += new
        total_dupes += dupes

        print(
            f"  [{window_num}/{num_windows}]"
            f"  {window_start.strftime('%Y-%m-%d')} → {current_end.strftime('%Y-%m-%d')}"
            f"  fetched={fetched:>6}  new={new:>6}  dupes={dupes:>4}"
            f"  | total: {total_fetched:>8} new, {total_dupes:>6} dupes",
            flush=True,
        )

        current_end = window_start

    return total_fetched, total_new, total_dupes


async def run_cron_sync(
    client: httpx.AsyncClient,
    window_days: int,
    page_size: int,
    max_dupes: int,
    lookback_days: int,
    seen: dict[tuple, int],
    stats: dict[str, dict],
) -> tuple[int, int, int]:
    """Recent windows backwards, stops after max_dupes consecutive duplicate records."""
    now = datetime.now(UTC)
    oldest = now - timedelta(days=lookback_days)
    current_end = now + timedelta(days=1)
    total_days = (current_end - oldest).days
    num_windows = (total_days + window_days - 1) // window_days

    total_fetched = 0
    total_new = 0
    total_dupes = 0
    consecutive_dupes = 0
    window_num = 0

    print(f"  {num_windows} windows to process ({total_days} days)\n")

    while current_end > oldest:
        window_start = max(current_end - timedelta(days=window_days), oldest)
        window_num += 1

        fetched, new, dupes = await fetch_window(
            client, window_start, current_end, page_size, seen, stats
        )

        total_fetched += fetched
        total_new += new
        total_dupes += dupes

        # Track consecutive all-duplicate windows
        if fetched > 0 and new == 0:
            consecutive_dupes += dupes
        else:
            consecutive_dupes = 0

        stopped = ""
        if consecutive_dupes >= max_dupes:
            stopped = "  ** STOP **"

        print(
            f"  [{window_num}/{num_windows}]"
            f"  {window_start.strftime('%Y-%m-%d')} → {current_end.strftime('%Y-%m-%d')}"
            f"  fetched={fetched:>6}  new={new:>6}  dupes={dupes:>4}"
            f"  | total: {total_fetched:>8} new, {total_dupes:>6} dupes"
            f"  (consec_dupes={consecutive_dupes}){stopped}",
            flush=True,
        )

        if consecutive_dupes >= max_dupes:
            break

        current_end = window_start

    return total_fetched, total_new, total_dupes


def print_summary(
    total_fetched: int,
    total_new: int,
    total_dupes: int,
    stats: dict[str, dict],
) -> None:
    """Print final per-sensor-tag summary table."""
    print(f"\nTotal records fetched: {total_fetched}")
    print(f"Total unique: {total_new}")
    print(f"Total duplicates: {total_dupes}")
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


async def main():
    args = parse_args()

    print("=" * 80)
    print("SPoHF API Sync Validation")
    print("=" * 80)
    print(f"  Mode:            {args.mode}")
    print(f"  Window days:     {args.window_days}")
    print(f"  Page size:       {args.page_size}")
    if args.mode == "cron":
        print(f"  Lookback days:   {args.cron_lookback_days}")
        print(f"  Max dupes:       {args.max_dupes}")
    print(f"  API:             {BASE_URL}")
    print("  Params:          timestamp_from / timestamp_until (new contract)")
    print("=" * 80)
    print()

    seen: dict[tuple, int] = defaultdict(int)
    stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "duplicates": 0, "min": None, "max": None}
    )

    async with httpx.AsyncClient() as client:
        if args.mode == "full":
            total_fetched, total_new, total_dupes = await run_full_sync(
                client, args.window_days, args.page_size, seen, stats
            )
        else:
            total_fetched, total_new, total_dupes = await run_cron_sync(
                client,
                args.window_days,
                args.page_size,
                args.max_dupes,
                args.cron_lookback_days,
                seen,
                stats,
            )

    print_summary(total_fetched, total_new, total_dupes, stats)


if __name__ == "__main__":
    asyncio.run(main())
