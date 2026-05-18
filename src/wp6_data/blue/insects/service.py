"""Blue's binding of the shared manual-ingest service.

The single source of truth for blue's manual-ingest wiring: the insect
descriptor, blue's categorical column (``project``) and blue's post-apply
cache invalidation. Both the CLI and the admin web routes build their
service through :func:`build_insect_service` so there is exactly one apply
path and one place that knows blue's bindings (mirrors red's
``red/sijia/service.py``).
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from wp6_data.blue.insects.source import INSECTS
from wp6_data.shared.manual_ingest import ManualIngestService
from wp6_data.shared.upload_storage import UploadStorage


def _invalidate_blue_caches() -> None:
    """Drop blue's cached sensor summaries after an insect apply.

    Blue's only cross-request cache is the shared sensor-summary TTLCache
    (keyed ``blue:*``); clearing it makes the next dashboard/home request
    see the just-applied insect rows instead of pre-upload stale data.
    """
    from wp6_data.shared.sensor_summary import invalidate

    invalidate()


def build_insect_service(
    pool: AsyncConnectionPool, storage: UploadStorage,
) -> ManualIngestService:
    """The insect manual-ingest service, keyed by blue's ``project`` column."""
    return ManualIngestService(
        pool=pool,
        storage=storage,
        source=INSECTS,
        column="project",
        post_apply_hook=_invalidate_blue_caches,
    )
