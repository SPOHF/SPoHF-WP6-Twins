"""Build orchestration for the risk cache (issue 015).

The single fetch → evaluate → persist path, reused by the admin Rebuild and
Update actions (and, later, a scheduled job). Kept thin and separate from the
route so the web layer only deals with HTTP, and so the same build can run
headless. ``evaluate`` itself stays pure; this is the I/O wrapper around it.
"""

from __future__ import annotations

from datetime import datetime

from wp6_data.db.pool import get_pool
from wp6_data.red import deps
from wp6_data.red.db import wire_physical_id
from wp6_data.red.multi_height.data import load_wire_readings
from wp6_data.red.risk import store
from wp6_data.red.risk.config import load_risk_thresholds
from wp6_data.red.risk.engine import RiskEvaluation, evaluate


async def build_range(wire: str, start_utc: datetime, end_utc: datetime) -> RiskEvaluation:
    """Fetch one wire's readings for a UTC window, evaluate, and persist.

    Replaces the window's episodes and refreshes the wire's state snapshot.
    Returns the evaluation (handy for logging/cron).
    """
    df = await load_wire_readings(start=start_utc, end=end_utc)
    if not df.empty:
        df = df[df["device"].map(wire_physical_id) == wire]

    thresholds = load_risk_thresholds(deps._METADATA_PATH)
    tz = deps.base_settings.display_timezone
    evaluation = evaluate(df, deps.growth_sections, thresholds, tz)
    await store.persist_build(get_pool(), wire, start_utc, end_utc, evaluation)
    return evaluation
