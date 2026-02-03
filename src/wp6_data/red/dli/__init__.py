"""DLI (Daily Light Integral) calculation and optimization module."""

from wp6_data.red.dli.calculator import calculate_daily_dli, calculate_hourly_par
from wp6_data.red.dli.model import (
    LightCorrelationModel,
    ModelStats,
    StageStats,  # noqa: F401
    TwoStageLightModel,  # noqa: F401
    get_model,
    predict_indoor_par,
)
from wp6_data.red.dli.optimizer import (
    OptimizationParams,
    OptimizedSchedule,
    calculate_optimal_schedule,
    compare_actual_vs_optimal,
    schedule_to_dataframe,
)
from wp6_data.red.dli.weather import (
    OpenMeteoClient,
    estimate_daily_natural_dli,
    estimate_indoor_par,
)

__all__ = [
    "calculate_daily_dli",
    "calculate_hourly_par",
    "calculate_optimal_schedule",
    "compare_actual_vs_optimal",
    "estimate_daily_natural_dli",
    "estimate_indoor_par",
    "get_model",
    "LightCorrelationModel",
    "ModelStats",
    "OpenMeteoClient",
    "OptimizationParams",
    "OptimizedSchedule",
    "predict_indoor_par",
    "schedule_to_dataframe",
]
