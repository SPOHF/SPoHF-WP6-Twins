"""Admin upload UI for the Sijia (Neurath) manual measurement source.

The router (admin-gated ``/sources/sijia`` with preview/apply/history) and
the ``/status`` card are produced by the shared manual-ingest factory from
the Sijia ``ManualSource`` descriptor. URLs and behaviour are unchanged from
the pre-extraction red-only implementation.
"""

from wp6_data.red.routes.sijia.deps import get_sijia_service
from wp6_data.red.sijia.source import SIJIA
from wp6_data.shared.manual_ingest import make_source_router

router = make_source_router(SIJIA, get_sijia_service)
