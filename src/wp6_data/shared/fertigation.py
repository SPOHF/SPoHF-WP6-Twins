"""Shared fertigation helpers."""

from pathlib import Path


def resolve_fertigation_csv_path(configured_path: str | None) -> Path:
    """Resolve fertigation events CSV path from optional configured value."""
    configured = (configured_path or "").strip()
    if configured:
        p = Path(configured)
        return p if p.is_absolute() else Path.cwd() / p
    return Path.cwd() / "uploads-blue" / "fertigation" / "fertigation_events.csv"
