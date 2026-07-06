"""Crop-climate frontend assets (CSS/JS) kept as real files in ``static/red/``.

Both are tiny, so they are loaded at import time and embedded inline in the
page; keeping them as files makes them editable and lintable as CSS/JS.
"""

from pathlib import Path

# parents[4] of src/wp6_data/red/multi_height/assets.py is the repo root
_STATIC_RED = Path(__file__).resolve().parents[4] / "static" / "red"


def _load(filename: str) -> str:
    return (_STATIC_RED / filename).read_text()


CROP_CLIMATE_JS = f"<script>\n{_load('crop_climate.js')}</script>\n"
CROP_CLIMATE_STYLE = f"<style>\n{_load('crop_climate.css')}</style>\n"
