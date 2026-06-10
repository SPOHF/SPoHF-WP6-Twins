"""Treatment metadata loaded from sensor_overview_SPoHF.csv."""

import csv
from functools import lru_cache
from pathlib import Path

_CSV_PATH = Path(__file__).parent.parent.parent / "sensor_overview_SPoHF.csv"

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
    "Ca":              "#dc2626",  # red           — calcium
    "G_K":             "#0f766e",  # deep teal     — generative-K regime
    "V_CA":            "#fb7185",  # rose          — vegetative-Ca regime
    "V_CA_G_BrPK":     "#7c2d12",  # brown         — staged mixed regime
    "V_K_G_CaBrP":     "#4c1d95",  # indigo        — staged mixed regime
    "Ca1":             "#f97316",  # orange
    "Weather Station": "#111827",  # near-black    — outdoor reference
}
_FALLBACK_COLOR = "#94a3b8"


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
