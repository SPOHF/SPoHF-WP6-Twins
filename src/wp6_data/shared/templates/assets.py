"""Frontend assets (CSS/JS) served from ``static/shared/``.

Large assets are referenced by URL (browser-cacheable, debuggable in
devtools); tiny ones — notably the pre-paint theme snippet — are loaded at
import time and embedded inline. Keeping them as real files makes them
editable and lintable as CSS/JS either way.
"""

from functools import cache
from pathlib import Path

# parents[4] of src/wp6_data/shared/templates/assets.py is the repo root
_STATIC_SHARED = Path(__file__).resolve().parents[4] / "static" / "shared"


def _load(filename: str) -> str:
    return (_STATIC_SHARED / filename).read_text(encoding="utf-8")


@cache
def asset_url(filename: str) -> str:
    """URL for a shared static asset, with an mtime cache-buster."""
    mtime = int((_STATIC_SHARED / filename).stat().st_mtime)
    return f"/static/shared/{filename}?v={mtime}"


BASE_CSS = _load("base.css")
THEME_JS = _load("theme.js")
TOGGLE_JS = _load("toggle.js")
EXPLORE_TABS_JS = _load("explore_tabs.js")
TABLE_SORT_JS = _load("table_sort.js")
UNIFIED_CHART_JS = _load("unified_chart.js")
DASHBOARD_CSS = _load("dashboard.css")
DASHBOARD_JS = _load("dashboard.js")
SAVE_TO_DASHBOARD_JS = _load("save_to_dashboard.js")
