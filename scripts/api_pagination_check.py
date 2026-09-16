#!/usr/bin/env python3

"""Validate that SPoHF datalake offset pagination is stable/ordered.

Historical bug: the /api/v1/data/<endpoint> API returned rows in an unstable
order across requests, so `from`/`size` offset pagination skipped and duplicated
rows. This script proves whether that's fixed by checking, over a fixed historical
window (stale data => stable between requests):

  1. Paginated fetch (small page size, many requests) vs single big-page fetch
     yield the SAME SET of records -> no rows skipped, none duplicated.
  2. The paginated stream has no duplicate keys within itself.
  3. Whether the stream is monotonically ordered by datetime_measure (diagnostic
     for WHY: a real ORDER BY is what makes offset pagination safe).

Record identity = (sensor_id, sensor_tag, datetime_measure, value), the same key
the sync dedup logic relies on.

Requires WP6_API_TOKEN (and optional WP6_API_BASE_URL) in env or .env.
"""

import argparse
import asyncio
import os
from datetime import UTC, datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("WP6_API_BASE_URL", "https://backoffice.spohf.com").rstrip("/")
TOKEN = os.environ["WP6_API_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}


def key(r: dict) -> tuple:
    return (
        r.get("sensor_id", "?"),
        r.get("sensor_tag", "?"),
        r.get("datetime_measure", ""),
        str(r.get("value", "")),
    )


async def fetch_page(
    client: httpx.AsyncClient, endpoint: str, t_from: datetime, t_to: datetime,
    offset: int, size: int,
) -> dict:
    url = f"{BASE_URL}/api/v1/data/{endpoint}"
    params = {
        "timestamp_from": t_from.isoformat(),
        "timestamp_until": t_to.isoformat(),
        "size": str(size),
        "from": str(offset),
    }
    resp = await client.get(url, params=params, headers=HEADERS, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def fetch_all(
    client: httpx.AsyncClient, endpoint: str, t_from: datetime, t_to: datetime,
    page_size: int,
) -> list[dict]:
    """Paginate the window, returning rows in the exact order received."""
    rows: list[dict] = []
    offset = 0
    pages = 0
    while True:
        data = await fetch_page(client, endpoint, t_from, t_to, offset, page_size)
        results = data.get("results", [])
        count = data.get("count", len(results))
        if not results:
            break
        rows.extend(results)
        pages += 1
        if count < page_size:
            break
        offset += page_size
    print(f"    {len(rows)} rows over {pages} page(s) at page_size={page_size}")
    return rows


def monotonic_report(rows: list[dict]) -> str:
    """Describe ordering of datetime_measure across the received stream."""
    dts = [r.get("datetime_measure", "") for r in rows]
    asc = all(dts[i] <= dts[i + 1] for i in range(len(dts) - 1))
    desc = all(dts[i] >= dts[i + 1] for i in range(len(dts) - 1))
    if asc:
        return "monotonic ASC by datetime_measure"
    if desc:
        return "monotonic DESC by datetime_measure"
    # find first break
    for i in range(len(dts) - 1):
        if not (dts[i] <= dts[i + 1]) and not (dts[i] >= dts[i + 1]):
            continue
    breaks = sum(
        1 for i in range(len(dts) - 1)
        if not (dts[i] <= dts[i + 1]) and not (dts[i] >= dts[i + 1])
    )
    return f"NOT monotonic by datetime_measure ({breaks} direction flips)"


# The API is Elasticsearch-backed: max_result_window = 10000 (from + size <= 10000).
# So a single request can return at most CAP rows; we need a window under that to
# fetch the whole set in one request as the comparison baseline.
CAP = 10000


async def find_window(
    client: httpx.AsyncClient, endpoint: str, min_rows: int,
) -> tuple[datetime, datetime, int] | None:
    """Walk back day-by-day from now to find a window with min_rows..CAP-1 rows."""
    end = datetime.now(UTC) + timedelta(days=1)
    for _ in range(800):  # up to ~2 years back
        start = end - timedelta(days=1)
        big = await fetch_page(client, endpoint, start, end, 0, CAP)
        total = len(big.get("results", []))
        if min_rows <= total < CAP:
            return start, end, total
        end = start
    return None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="yookr-data")
    parser.add_argument("--page-size", type=int, default=50,
                        help="Small page size to force many requests (default 50)")
    parser.add_argument("--min-rows", type=int, default=300,
                        help="Require a window with at least this many rows")
    args = parser.parse_args()

    print("=" * 78)
    print("SPoHF datalake pagination stability check")
    print(f"  API:       {BASE_URL}")
    print(f"  Endpoint:  {args.endpoint}")
    print(f"  page_size: {args.page_size}  (small -> forces multi-request pagination)")
    print("=" * 78)

    async with httpx.AsyncClient() as client:
        print("\nFinding a dense historical window (stable data, multi-page)...")
        found = await find_window(client, args.endpoint, args.min_rows)
        if not found:
            print("  No window with enough rows found. Try a lower --min-rows.")
            return 2
        t_from, t_to, total = found
        print(f"  Using {t_from:%Y-%m-%d} -> {t_to:%Y-%m-%d}  (~{total} rows)")

        print("\n[A] Single big-page fetch (one request, one ordering):")
        single = await fetch_all(client, args.endpoint, t_from, t_to, page_size=CAP)

        print(f"\n[B] Paginated fetch (page_size={args.page_size}, many requests):")
        paged = await fetch_all(client, args.endpoint, t_from, t_to, args.page_size)

        single_keys = [key(r) for r in single]
        paged_keys = [key(r) for r in paged]
        single_set = set(single_keys)
        paged_set = set(paged_keys)

        missing = single_set - paged_set      # rows the paginator SKIPPED
        extra = paged_set - single_set         # rows that appeared only when paged
        # duplicates within paginated stream:
        seen: dict[tuple, int] = {}
        for k in paged_keys:
            seen[k] = seen.get(k, 0) + 1
        dupes = {k: c for k, c in seen.items() if c > 1}

        print("\n" + "=" * 78)
        print("RESULTS")
        print("=" * 78)
        print(f"  single-fetch unique rows : {len(single_set)}")
        print(f"  paginated   unique rows : {len(paged_set)}")
        print(f"  paginated   total rows  : {len(paged_keys)}")
        print(f"  rows SKIPPED by paginator (in single, not paged): {len(missing)}")
        print(f"  rows EXTRA in paginator  (in paged, not single) : {len(extra)}")
        print(f"  duplicate keys within paginated stream          : {len(dupes)}")
        print(f"  ordering of received stream: {monotonic_report(single)}")

        ok = not missing and not extra and not dupes and len(single_set) == len(single_keys)
        print("\n" + ("  ✅ PAGINATION IS STABLE — bug appears FIXED."
                       if ok else
                       "  ❌ PAGINATION IS UNRELIABLE — skips/dupes detected."))
        if missing:
            ex = list(missing)[:3]
            print(f"     e.g. skipped: {ex}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
