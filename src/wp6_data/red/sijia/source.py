"""The Sijia ``ManualSource`` descriptor — red's per-source seam.

This is the *only* place that names the Sijia specifics the shared
capability needs: its slug/categorical value (``sijia``), display copy, the
``.xlsx`` suffix, and the parser entry points. The shared service, storage,
routes, history and CLI are all driven from this.
"""

from wp6_data.red.sijia.parser import SijiaParseError, parse, validate
from wp6_data.shared.manual_ingest.source import ManualSource

SIJIA = ManualSource(
    slug="sijia",
    categorical_value="sijia",
    display_name="Sijia (Neurath)",
    file_suffix=".xlsx",
    accept=".xlsx",
    row_noun="Excel rows",
    upload_hint="Upload a Neurath measurements .xlsx file.",
    parse=parse,
    validate=validate,
    parse_error=SijiaParseError,
)
