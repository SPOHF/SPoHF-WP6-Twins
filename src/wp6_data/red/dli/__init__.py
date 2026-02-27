"""DLI (Daily Light Integral) calculation and optimization module."""

from wp6_data.red.dli.aggregation import (
    add_day_of_year_features,
    aggregate_to_daily,
    align_daily_dataframes,
    align_outdoor_to_indoor_daily,
    align_weather_to_outdoor_daily,
    encode_day_of_year,
)
from wp6_data.red.dli.calculator import (
    calculate_daily_dli,
    calculate_dli_trendline,
    calculate_hourly_par,
    calculate_lamp_contribution,
    estimate_hourly_natural_par,
    par_sum_to_dli,
)
from wp6_data.red.dli.constants import (
    DEFAULT_PHOTOPERIOD_THRESHOLD,
    DEFAULT_TRAINING_START,
    MIN_INDOOR_PAR,
    MIN_OUTDOOR_LUX,
    NATURAL_LIGHT_SENSOR,
    SECONDS_PER_HOUR,
    TOTAL_LIGHT_SENSOR,
    UMOL_TO_MOL,
)
from wp6_data.red.dli.diagnostics import (
    align_weather_outdoor_hourly,
    analyze_reporting_frequency,
    calculate_correlation_comparison,
    derive_daily_lamp_profile,
    subtract_lamp_from_sensor,
)
from wp6_data.red.dli.model import (
    LightCorrelationModel,
    ModelStats,
    StageStats,  # noqa: F401
    TwoStageLightModel,  # noqa: F401
    get_model,
)
from wp6_data.red.dli.schedule import (
    build_lamp_schedules,
    compute_daily_predicted_dli,
    distribute_dli_across_hours,
    estimate_remaining_dli,
    fetch_weather_for_range,
    infer_lamp_schedule_hourly,
    predict_natural_dli_from_weather,
    prepare_daily_dli_summary,
    try_infer_lamp_from_day,
)
from wp6_data.red.dli.weather import OpenMeteoClient

__all__ = [
    # Constants
    "DEFAULT_PHOTOPERIOD_THRESHOLD",
    "DEFAULT_TRAINING_START",
    "MIN_INDOOR_PAR",
    "MIN_OUTDOOR_LUX",
    "NATURAL_LIGHT_SENSOR",
    "SECONDS_PER_HOUR",
    "TOTAL_LIGHT_SENSOR",
    "UMOL_TO_MOL",
    # Calculator functions
    "calculate_daily_dli",
    "calculate_dli_trendline",
    "calculate_hourly_par",
    "calculate_lamp_contribution",
    "estimate_hourly_natural_par",
    "par_sum_to_dli",
    # Aggregation functions
    "add_day_of_year_features",
    "aggregate_to_daily",
    "align_daily_dataframes",
    "align_outdoor_to_indoor_daily",
    "align_weather_to_outdoor_daily",
    "encode_day_of_year",
    # Schedule functions
    "build_lamp_schedules",
    "compute_daily_predicted_dli",
    "distribute_dli_across_hours",
    "estimate_remaining_dli",
    "fetch_weather_for_range",
    "infer_lamp_schedule_hourly",
    "predict_natural_dli_from_weather",
    "prepare_daily_dli_summary",
    "try_infer_lamp_from_day",
    # Diagnostics functions
    "align_weather_outdoor_hourly",
    "analyze_reporting_frequency",
    "calculate_correlation_comparison",
    "derive_daily_lamp_profile",
    "subtract_lamp_from_sensor",
    # Model classes and functions
    "get_model",
    "LightCorrelationModel",
    "ModelStats",
    "OpenMeteoClient",
]
