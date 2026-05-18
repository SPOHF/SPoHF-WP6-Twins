"""Red-bound facade over the shared :class:`ManualIngestService`.

The transactional apply, audit, prune and bookkeeping now live in
``wp6_data.shared.manual_ingest``. Red keeps this ``ManualIngestService``
name/shape so existing callers and tests are unchanged — it just binds the
Sijia descriptor, red's categorical column (``source``) and red's in-process
cache invalidation as the post-apply hook.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from wp6_data.red.sijia.source import SIJIA
from wp6_data.shared.manual_ingest.service import ApplyResult
from wp6_data.shared.manual_ingest.service import (
    ManualIngestService as _SharedManualIngestService,
)
from wp6_data.shared.upload_storage import UploadStorage

__all__ = ["ApplyResult", "ManualIngestService"]


def _invalidate_red_caches() -> None:
    """Drop RedSensorProvider's in-process caches after a Sijia apply.

    Imported lazily to avoid a provider↔service import cycle.
    """
    from wp6_data.red.provider import invalidate_caches

    invalidate_caches()


class ManualIngestService(_SharedManualIngestService):
    """The Sijia manual-ingest service (red twin).

    Behaviour is identical to the pre-extraction service; only the plumbing
    is shared. ``readings`` is keyed by red's ``source`` column.
    """

    def __init__(
        self, pool: AsyncConnectionPool, storage: UploadStorage,
    ) -> None:
        super().__init__(
            pool=pool,
            storage=storage,
            source=SIJIA,
            column="source",
            post_apply_hook=_invalidate_red_caches,
        )
