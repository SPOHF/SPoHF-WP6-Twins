"""Humidity conversions for the per-height deviation model.

Relative humidity is not comparable between two heights at different
temperatures: the same air carries a different RH as it warms, so an "RH
deviation" down the wire mixes a real moisture difference with a temperature
difference. Absolute humidity does not have that problem — it is a property of
the air itself — so the per-height deviation is fitted on absolute humidity and
converted back to RH using the *predicted* temperature at that height.

The conversion back through the same saturation curve is also what keeps a
later VPD consistent with the temperature and humidity it is derived from.
Saturation vapour pressure comes from ``risk.metrics`` rather than a second
Tetens implementation here.
"""

from __future__ import annotations

import numpy as np

from wp6_data.red.risk.metrics import saturation_vapor_pressure_kpa

# Specific gas constant for water vapour, J/(kg·K).
WATER_VAPOUR_GAS_CONSTANT = 461.5
KELVIN_OFFSET = 273.15
KPA_TO_PA = 1000.0
KG_TO_G = 1000.0


def absolute_humidity(temp_c, rh_pct):
    """Absolute humidity (g/m³) from temperature (°C) and relative humidity (%).

    Accepts scalars or arrays.
    """
    temp_c = np.asarray(temp_c, dtype=float)
    rh_pct = np.asarray(rh_pct, dtype=float)
    vapour_pressure_pa = (
        saturation_vapor_pressure_kpa(temp_c) * KPA_TO_PA * (rh_pct / 100.0)
    )
    kelvin = temp_c + KELVIN_OFFSET
    return (
        vapour_pressure_pa / (WATER_VAPOUR_GAS_CONSTANT * kelvin)
    ) * KG_TO_G


def relative_humidity(temp_c, absolute_g_m3):
    """Relative humidity (%) from temperature (°C) and absolute humidity (g/m³).

    The inverse of :func:`absolute_humidity`. Clipped to 0-100: the arithmetic
    can land marginally outside when a predicted temperature and a predicted
    moisture content disagree slightly, and a humidity of 101% is a rounding
    artefact, not a measurement.
    """
    temp_c = np.asarray(temp_c, dtype=float)
    absolute_g_m3 = np.asarray(absolute_g_m3, dtype=float)
    kelvin = temp_c + KELVIN_OFFSET
    vapour_pressure_kpa = (
        (absolute_g_m3 / KG_TO_G) * WATER_VAPOUR_GAS_CONSTANT * kelvin
    ) / KPA_TO_PA
    return np.clip(
        100.0 * vapour_pressure_kpa / saturation_vapor_pressure_kpa(temp_c), 0.0, 100.0
    )
