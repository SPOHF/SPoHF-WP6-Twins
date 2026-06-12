"""Blue fertigation helpers."""

import csv
from datetime import date
from pathlib import Path


def resolve_fertigation_csv_path(
    configured_path: str | None,
    upload_dir: str | None = None,
) -> Path:
    """Resolve fertigation events CSV path.

    Priority:
    1) Explicit configured path.
    2) Most recent manual upload under {upload_dir}/fertigation_events/*.csv.
    3) Workspace fallback uploads-blue/fertigation/fertigation_events.csv.
    """
    configured = (configured_path or "").strip()
    if configured:
        p = Path(configured)
        return p if p.is_absolute() else Path.cwd() / p

    if upload_dir:
        source_dir = Path(upload_dir) / "fertigation_events"
        latest_csv = max(
            source_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            default=None,
        )
        if latest_csv is not None:
            return latest_csv

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
