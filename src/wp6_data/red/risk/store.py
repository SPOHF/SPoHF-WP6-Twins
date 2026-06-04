"""Persistence for the rebuildable risk cache (red ADR 0002, issue 015).

Writes the engine's output to two red-TSDB tables: ``risk_episodes`` (the
recomputable log) and ``risk_state`` (latest per-section verdict the page reads).
A build *replaces* a date range rather than appending, so re-running over the
same range with the same thresholds is idempotent (the cache is reproducible,
not immutable). All of a build's writes happen in one transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .engine import RiskEvaluation

_INSERT_EPISODE = """
INSERT INTO risk_episodes
    (wire, height, label, risk, start_time, end_time, peak, thresholds)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_UPSERT_STATE = """
INSERT INTO risk_state
    (wire, height, label, height_dli, vpd_latest, vpd_in_band,
     wet_hours_latest, fungal_active, co2_latest, co2_depleted,
     canopy_deficit, built_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (wire, height) DO UPDATE SET
    label            = EXCLUDED.label,
    height_dli       = EXCLUDED.height_dli,
    vpd_latest       = EXCLUDED.vpd_latest,
    vpd_in_band      = EXCLUDED.vpd_in_band,
    wet_hours_latest = EXCLUDED.wet_hours_latest,
    fungal_active    = EXCLUDED.fungal_active,
    co2_latest       = EXCLUDED.co2_latest,
    co2_depleted     = EXCLUDED.co2_depleted,
    canopy_deficit   = EXCLUDED.canopy_deficit,
    built_at         = NOW()
"""


def _to_dt(ts: Any) -> datetime | None:
    """Coerce a pandas Timestamp (or None) to a stdlib datetime for psycopg."""
    if ts is None:
        return None
    return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts


async def persist_build(
    pool: AsyncConnectionPool,
    wire: str,
    start: datetime,
    end: datetime,
    evaluation: RiskEvaluation,
) -> None:
    """Replace ``wire``'s episodes in ``[start, end)`` and refresh its state.

    One transaction: delete the range's episodes, insert the evaluation's, and
    upsert the per-section state snapshot.
    """
    episode_rows = [
        (
            wire, e.height, e.label, e.risk,
            _to_dt(e.start), _to_dt(e.end), float(e.peak), Jsonb(e.thresholds),
        )
        for e in evaluation.episodes
    ]
    state_rows = [
        (
            wire, s.height, s.label, s.height_dli, s.vpd_latest, s.vpd_in_band,
            s.wet_hours_latest, s.fungal_active, s.co2_latest, s.co2_depleted,
            s.canopy_deficit,
        )
        for s in evaluation.states
    ]

    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM risk_episodes "
            "WHERE wire = %s AND start_time >= %s AND start_time < %s",
            (wire, start, end),
        )
        if episode_rows:
            await cur.executemany(_INSERT_EPISODE, episode_rows)
        for row in state_rows:
            await cur.execute(_UPSERT_STATE, row)


async def read_state(pool: AsyncConnectionPool, wire: str) -> list[dict[str, Any]]:
    """Latest per-section verdict for ``wire`` (ordered by height)."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM risk_state WHERE wire = %s ORDER BY height", (wire,),
        )
        return list(await cur.fetchall())


async def read_episodes(
    pool: AsyncConnectionPool, wire: str, start: datetime, end: datetime,
) -> list[dict[str, Any]]:
    """Episodes for ``wire`` starting within ``[start, end)`` (chronological)."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM risk_episodes "
            "WHERE wire = %s AND start_time >= %s AND start_time < %s "
            "ORDER BY start_time, height, risk",
            (wire, start, end),
        )
        return list(await cur.fetchall())


async def read_episodes_overlapping(
    pool: AsyncConnectionPool, wire: str, start: datetime, end: datetime,
) -> list[dict[str, Any]]:
    """Episodes for ``wire`` that *overlap* ``[start, end)`` (chronological).

    Unlike :func:`read_episodes` (which filters on ``start_time``), this returns
    every episode whose span intersects the window — including one that began
    before ``start`` or is still ongoing (``end_time IS NULL``). That's what a
    single-day timeline needs: a risk present at midnight belongs on the day even
    though it started the night before.
    """
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM risk_episodes "
            "WHERE wire = %s AND start_time < %s "
            "AND (end_time IS NULL OR end_time >= %s) "
            "ORDER BY height, risk, start_time",
            (wire, end, start),
        )
        return list(await cur.fetchall())


async def last_built_at(pool: AsyncConnectionPool, wire: str) -> datetime | None:
    """When ``wire``'s state was last built, or ``None`` if never."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT max(built_at) FROM risk_state WHERE wire = %s", (wire,))
        row = await cur.fetchone()
        return row[0] if row else None


async def open_episode_floor(pool: AsyncConnectionPool, wire: str) -> datetime | None:
    """Earliest start of an unresolved (``end_time IS NULL``) episode, or ``None``.

    An incremental update starts no later than this so an episode still open at
    the previous build boundary is recomputed as one whole span (and closed if it
    has since resolved), instead of being orphaned as permanently "ongoing".
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT min(start_time) FROM risk_episodes "
            "WHERE wire = %s AND end_time IS NULL",
            (wire,),
        )
        row = await cur.fetchone()
        return row[0] if row else None
