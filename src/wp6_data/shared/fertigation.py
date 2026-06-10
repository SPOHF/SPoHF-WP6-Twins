"""Shared fertigation helpers."""

import csv
from datetime import date
from pathlib import Path


def resolve_fertigation_csv_path(configured_path: str | None) -> Path:
    """Resolve fertigation events CSV path from optional configured value."""
    configured = (configured_path or "").strip()
    if configured:
        p = Path(configured)
        return p if p.is_absolute() else Path.cwd() / p
    return Path.cwd() / "uploads-blue" / "fertigation" / "fertigation_events.csv"


def load_fertigation_event_days(path: Path) -> list[date]:
    """Load unique fertigation event days from CSV (volume_ml_per_plant > 0)."""
    if not path.exists():
        return []

    import math

    days: set[date] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
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
