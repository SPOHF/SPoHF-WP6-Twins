"""The insect ``ManualSource`` descriptor — blue's per-source seam.

The only place that names the insect specifics the shared capability needs:
slug/categorical value (``insects`` → blue ``readings.project``), display
copy, the ``.csv`` suffix, and the parser entry points. The shared service,
storage, routes, history and CLI are all driven from this.
"""

from wp6_data.blue.insects.parser import InsectParseError, parse, validate
from wp6_data.shared.manual_ingest.source import ManualSource

INSECTS = ManualSource(
    slug="insects",
    categorical_value="insects",
    display_name="Insect traps",
    file_suffix=".csv",
    accept=".csv,text/csv",
    row_noun="CSV rows",
    upload_hint=(
        "Upload an insect-trap counts .csv file "
        "(header: timestamp,total_insects,suzukii)."
    ),
    parse=parse,
    validate=validate,
    parse_error=InsectParseError,
)
