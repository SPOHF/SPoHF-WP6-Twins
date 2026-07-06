"""Red multi-height domain package.

Data access, SVG layout parsing, HTML cell builders, Plotly figure builders and
the crop-climate day view-model behind the ``/multi_height`` routes.
"""

from .data import (
    USE_LATEST_DATE_IN_DATA,
    compute_sensor_metrics,
    day_window_utc,
    filter_for_day,
    latest_wire_date,
    load_wire_readings,
    load_wire_sensor_data,
    series_for,
    wire_ids,
)
from .view_model import (
    CropClimateDay,
    SectionView,
    assemble_crop_climate_day,
    build_crop_climate_day,
)

__all__ = [
    "USE_LATEST_DATE_IN_DATA",
    "CropClimateDay",
    "SectionView",
    "assemble_crop_climate_day",
    "build_crop_climate_day",
    "compute_sensor_metrics",
    "day_window_utc",
    "filter_for_day",
    "latest_wire_date",
    "load_wire_readings",
    "load_wire_sensor_data",
    "series_for",
    "wire_ids",
]
