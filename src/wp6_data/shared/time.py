"""Display timezone helpers — convert UTC to local for frontend display."""

from datetime import datetime
from zoneinfo import ZoneInfo

from wp6_data.config import Settings

_tz: ZoneInfo | None = None


def display_tz() -> ZoneInfo:
    """Get the configured display timezone (cached)."""
    global _tz
    if _tz is None:
        _tz = ZoneInfo(Settings().display_timezone)
    return _tz


def to_local_isoformat(dt: datetime) -> str:
    """Convert a UTC datetime to a timezone-naive local ISO string for Plotly.

    Plotly.js displays timestamps in UTC. By returning a naive local-time string,
    Plotly renders it as-is — effectively showing the configured display timezone.
    """
    local_dt = dt.astimezone(display_tz())
    return local_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
