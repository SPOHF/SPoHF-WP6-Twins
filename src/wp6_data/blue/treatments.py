"""Blue treatment vocabulary — canonical codes, ordering, colours, aliases.

The fertiliser treatments are blue's central domain concept: every data source
(automated sensors, ``long_data`` lab measurements, the fertilizer-strategy
spreadsheet) labels its rows with a treatment, each in its own vocabulary.
This module owns the canonical codes and everything keyed on them; per-source
alias maps translate source labels into the canonical codes on the way in.
"""

import csv
from functools import lru_cache
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "sensor_overview_SPoHF.csv"

# Comparable fertilizer strategies kept adjacent for easy visual comparison.
# The 2025 sub-strategy codes (V_CA, G_K, …) are the canonical device names as
# stored in the DB by long_data ingest; they are not the same as Ca1/K1 etc.
TREATMENT_ORDER: tuple[str, ...] = (
    "Std",
    "Org1", "Org2",
    "Ca", "K",
    "V_CA", "G_K",
    "V_CA_G_BrPK", "V_K_G_CaBrP",
)

# Colour per fertiliser treatment (consistent across all monitor charts).
# Treatments within the same family use distinct hues, not just brightness.
TREATMENT_COLORS: dict[str, str] = {
    "Std":             "#6b7280",  # gray          — standard
    "K":               "#1d4ed8",  # deep blue     — potassium
    "K1":              "#7c3aed",  # violet
    "K2":              "#db2777",  # pink/magenta
    "K3":              "#0891b2",  # cyan/teal
    "Org1":            "#15803d",  # dark green    — organic
    "Org2":            "#84cc16",  # lime green
    "Ca":              "#dc2626",  # red           — calcium (V_Ca_G_Ca)
    "G_K":             "#0f766e",  # deep teal     — legacy code (V_-_G_K)
    "V_CA":            "#fb7185",  # rose          — legacy code (V_Ca_G_-)
    "V_CA_G_BrPK":     "#7c2d12",  # brown         — legacy code
    "V_K_G_CaBrP":     "#4c1d95",  # indigo        — legacy code
    "Weather Station": "#111827",  # near-black    — outdoor reference
}
_FALLBACK_COLOR = "#94a3b8"

# Source treatment labels (2024 English, 2025 Dutch/codes) → canonical code,
# reused from the automated sensors' `position` vocabulary. The four 2025
# phenological-stage regimes pass through unchanged (V_=vegetative stage,
# G_=generative stage); they are first-class treatments, not Ca/K variants.
LONG_DATA_TREATMENT_MAP: dict[str, str] = {
    "Organic 1": "Org1", "Organisch-1": "Org1",
    "Organic 2": "Org2", "Organisch-2": "Org2",
    "Standard": "Std", "Standaard": "Std",
    "Calcium": "Ca", "Ca": "Ca",
    "Kalium": "K", "K": "K",
    "G_K": "G_K",
    "V_CA": "V_CA",
    "V_CA_G_BrPK": "V_CA_G_BrPK",
    "V_K_G_CaBrP": "V_K_G_CaBrP",
}

# Row labels used in fertilizer_strategy_2025.xlsx → canonical code.
FERTILIZER_XLSX_TREATMENT_MAP: dict[str, str] = {
    "DCM (Org-1)": "Org1",
    "Den Ouden (Org-2)": "Org2",
    "Standaard (3rijen)": "Std",
    "V_Ca": "V_CA",
    "Ca": "Ca",
    "V_Ca_GBrPK": "V_CA_G_BrPK",
    "G_K": "G_K",
    "K": "K",
    "V_K_G_CaBrP": "V_K_G_CaBrP",
}


# Explicit overrides for devices that have no Fertilizer column in the CSV
_DEVICE_OVERRIDES: dict[str, str] = {
    "weatherstation": "Weather Station",
}


@lru_cache(maxsize=1)
def load_device_treatment_map() -> dict[str, str]:
    """Return {device_name: treatment_label} from the sensor overview CSV."""
    mapping: dict[str, str] = {}
    with open(_CSV_PATH, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # Force reading of the header row, then strip whitespace from field names
        # (the CSV has a leading space on " Fertilizer")
        _ = reader.fieldnames
        reader.fieldnames = [f.strip() for f in (reader.fieldnames or [])]
        for row in reader:
            device = (row.get("device_name") or "").strip()
            treatment = (row.get("Fertilizer") or "").strip()
            if device and treatment:
                mapping[device] = treatment
    mapping.update(_DEVICE_OVERRIDES)
    return mapping


def treatment_color(treatment: str) -> str:
    """Return the hex colour for a treatment label."""
    return TREATMENT_COLORS.get(treatment, _FALLBACK_COLOR)
