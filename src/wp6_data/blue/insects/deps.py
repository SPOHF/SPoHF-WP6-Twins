"""FastAPI dependency that constructs the per-request insect ingest service.

Mirrors red's ``red/routes/sijia/deps.py``; used by the shared route factory
when blue's insect upload routes are wired (Step 5).
"""

from pathlib import Path

from wp6_data.blue.insects.service import build_insect_service
from wp6_data.config import Settings
from wp6_data.db.pool import get_pool
from wp6_data.shared.manual_ingest import ManualIngestService
from wp6_data.shared.upload_storage import UploadStorage


def get_insect_service() -> ManualIngestService:
    settings = Settings()
    pool = get_pool()
    storage = UploadStorage(
        base_dir=Path(settings.blue_upload_dir), pool=pool,
    )
    return build_insect_service(pool, storage)
