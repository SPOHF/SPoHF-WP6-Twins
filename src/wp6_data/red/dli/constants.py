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

# The same two gates for the model's daily aggregates, which are time integrals
# rather than sums of readings (see calculator.integrate_over_time). Separate
# constants because the units are different — lux-hours and μmol/m², not counts
# — and because the two above are still what lamp.py measures a day against.
#
# Both say "this day saw essentially nothing", in the aggregate's own units.
# The reading-sum gates they replace could not: a day of genuine daylight
# sampled half as often fell below them, and a dark day sampled often enough
# passed. Red's dullest December day integrates to ~108,000 lux-hours and ~1
# mol/m², so each gate sits about two orders of magnitude below any real day.
MIN_OUTDOOR_LUX_HOURS = 1_000.0  # lux-hours (mean ~42 lux over a day)
MIN_INDOOR_PAR_INTEGRAL = 30_000.0  # μmol/m², i.e. a DLI of 0.03

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
SECONDS_PER_DAY = 86_400  # day → seconds

# Expected sensor cadence used when converting PAR sums to DLI from raw readings.
# Change only if sensor sampling interval truly changes in production.
READING_INTERVAL_SECONDS = 600  # ~10-minute PAR cadence
