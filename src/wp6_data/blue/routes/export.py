"""Blue dashboard CSV export endpoint."""

from wp6_data.blue.deps import EXPORT_DIR
from wp6_data.shared.export import make_download_router

router = make_download_router(EXPORT_DIR, sanitise=True)
