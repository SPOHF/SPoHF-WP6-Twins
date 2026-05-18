"""Admin upload UI for the blue insect-trap CSV source.

The admin-gated ``/sources/insects`` router (preview/apply/history) and the
``/status`` card are produced by the shared manual-ingest factory from the
insect ``ManualSource`` descriptor — the same factory red/Sijia uses. Blue's
OIDC session (see ``blue/dashboard.py``) backs the admin gating.
"""

from wp6_data.blue.insects.deps import get_insect_service
from wp6_data.blue.insects.source import INSECTS
from wp6_data.shared.manual_ingest import make_card, make_source_router

router = make_source_router(INSECTS, get_insect_service)
render_insect_card = make_card(INSECTS)
