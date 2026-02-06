"""Constants for DLI (Daily Light Integral) module."""

from datetime import date

# Sensor identifiers
NATURAL_LIGHT_SENSOR = "s2100-01-par"
TOTAL_LIGHT_SENSOR = "s2100-02-par"

# Photoperiod calculation threshold (μmol/m²/s)
DEFAULT_PHOTOPERIOD_THRESHOLD = 10.0

# Minimum values for filtering valid data
MIN_OUTDOOR_LUX = 1000  # Minimum daily lux sum for valid daylight
MIN_INDOOR_PAR = 100  # Minimum daily PAR sum for valid readings

# Training data start date (devices up and running)
DEFAULT_TRAINING_START = date(2025, 11, 1)

# Conversion factors
UMOL_TO_MOL = 1_000_000  # μmol to mol conversion factor
SECONDS_PER_HOUR = 3600
