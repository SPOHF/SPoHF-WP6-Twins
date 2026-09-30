"""Blue fertigation helpers."""

from __future__ import annotations

import csv
import io
import math
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from wp6_data.shared.blob import BlobStore

FERTIGATION_SOURCE = "fertigation_events"

#: Dev-machine fallback, used when nothing is configured and no upload exists.
WORKSPACE_FALLBACK = Path("uploads-blue") / "fertigation" / "fertigation_events.csv"


async def load_fertigation_csv(
    configured_path: str | None,
    store: BlobStore | None = None,
    pool: AsyncConnectionPool | None = None,
) -> bytes | None:
    """The fertigation events CSV, or ``None`` when there isn't one.

    Priority:

    1. An explicit configured path, read from the filesystem.
    2. The most recent manual upload for ``fertigation_events`` in ``store``.
    3. The workspace fallback, for a dev machine with neither.

    Returns bytes rather than a path because the uploads live in an object store
    now, not on a mounted volume (issue 061 phase 3).

    **Recency comes from the audit table, not from the object.** The previous
    version took the newest ``*.csv`` by mtime, which only worked because the
    files happened to sit on a filesystem — the names are sha256 hashes, so they
    carry no order of their own. ``manual_uploads.uploaded_at`` is the system of
    record for when an upload happened, so asking it is both correct and what
    the rest of the upload flow already relies on.
    """
    configured = (configured_path or "").strip()
    if configured:
        path = Path(configured)
        path = path if path.is_absolute() else Path.cwd() / path
        return _read_file(path)

    if store is not None and pool is not None:
        raw = await _latest_upload(store, pool)
        if raw is not None:
            return raw

    return _read_file(Path.cwd() / WORKSPACE_FALLBACK)


def _read_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


async def _latest_upload(
    store: BlobStore, pool: AsyncConnectionPool,
) -> bytes | None:
    """The newest un-pruned fertigation upload, by ``uploaded_at``."""
    from wp6_data.shared.upload_storage import stored_key

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT file_path FROM manual_uploads "
            "WHERE source = %s AND file_path IS NOT NULL "
            "ORDER BY uploaded_at DESC LIMIT 1",
            (FERTIGATION_SOURCE,),
        )
        row = await cur.fetchone()

    if row is None:
        return None
    try:
        return await store.try_get(stored_key(row[0]))
    except Exception:
        # An unreachable store means "no overlay available", which the page
        # already renders — not a reason to fail the whole chart.
        return None


def parse_fertigation_event_days(raw: bytes | None) -> list[date]:
    """Unique fertigation event days from CSV bytes (volume_ml_per_plant > 0)."""
    if not raw:
        return []

    days: set[date] = set()
    text = io.StringIO(raw.decode("utf-8-sig"), newline="")
    for row in csv.DictReader(text):
        day_raw = (row.get("date") or "").strip()
        if not day_raw:
            continue
        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            continue

        vol_raw = (row.get("volume_ml_per_plant") or "").strip()
        try:
            volume = float(vol_raw)
        except ValueError:
            continue
        if not math.isfinite(volume) or volume <= 0:
            continue
        days.add(day)

    return sorted(days)
