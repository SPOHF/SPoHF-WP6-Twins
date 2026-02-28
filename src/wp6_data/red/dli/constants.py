"""Constants for DLI (Daily Light Integral) module."""

from datetime import date

# Sensor identifiers used across DLI routes/model logic.
# Changing these switches data sources and can change behavior significantly.
NATURAL_LIGHT_SENSOR = "s2100-01-par"
TOTAL_LIGHT_SENSOR = "s2100-02-par"
WEATHER_STATION_SENSOR = "s1000"

# Calculation threshold for photoperiod detection (μmol/m²/s).
# Impacts derived day-length metrics and downstream summaries.
DEFAULT_PHOTOPERIOD_THRESHOLD = 10.0

# Data-quality gates used in model fitting / attenuation logic.
# Treat as model-sensitive: adjust only with validation against historical results.
MIN_OUTDOOR_LUX = 1000  # Minimum daily lux sum to treat as valid daylight
MIN_INDOOR_PAR = 100  # Minimum daily PAR sum to treat as valid indoor signal

# First date considered valid for training data.
# Model behavior can change materially if this window is widened/narrowed.
DEFAULT_TRAINING_START = date(2025, 11, 1)

# View/runtime defaults (safe to tune for UX; should not change core physics/model math).
DEFAULT_FORECAST_CENTER_DAYS = 2  # today-2 ... today+2
DEFAULT_PERFORMANCE_LOOKBACK_DAYS = 30

# View classification thresholds for performance coloring (% absolute error).
# Primarily presentation-level; changing affects dashboards, not model predictions.
PERFORMANCE_ERROR_WARN_THRESHOLD_PCT = 15.0
PERFORMANCE_ERROR_HIGH_THRESHOLD_PCT = 30.0

# Unit/time conversion constants used by DLI equations.
# These are effectively immutable physical/time conversions and should not be changed.
UMOL_TO_MOL = 1_000_000  # μmol → mol
SECONDS_PER_HOUR = 3600  # hour → seconds

# Expected sensor cadence used when converting PAR sums to DLI from raw readings.
# Change only if sensor sampling interval truly changes in production.
READING_INTERVAL_SECONDS = 600  # ~10-minute PAR cadence
