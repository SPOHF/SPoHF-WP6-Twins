"""Red multi-height domain package.

Data access, SVG layout parsing, HTML cell builders, Plotly figure builders and
the day view-models behind the ``/multi_height`` routes — ``view_model`` for one
wire's growth sections, ``uniformity`` for every declared wire side by side.

Only the data and crop-climate seams are re-exported here; ``cells``, ``charts``,
``config`` and the uniformity modules are imported by path. ``config`` is
deliberately a leaf (it reads no data), so ``deps`` can load the twin's config at
import time without pulling this package's data layer in behind it.
"""

from .data import (
    compute_sensor_metrics,
    day_window_utc,
    filter_for_day,
    latest_wire_date,
    load_wire_readings,
    series_for,
)
from .view_model import (
    CropClimateDay,
    SectionView,
    assemble_crop_climate_day,
    build_crop_climate_day,
)

__all__ = [
    "CropClimateDay",
    "SectionView",
    "assemble_crop_climate_day",
    "build_crop_climate_day",
    "compute_sensor_metrics",
    "day_window_utc",
    "filter_for_day",
    "latest_wire_date",
    "load_wire_readings",
    "series_for",
]
