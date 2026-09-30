"""FastAPI dependency that constructs the per-request ManualIngestService."""


from wp6_data.config import RedSettings
from wp6_data.db.pool import get_pool
from wp6_data.red import deps as red_deps
from wp6_data.red.sijia.service import ManualIngestService
from wp6_data.shared.upload_storage import UploadStorage


def get_sijia_service() -> ManualIngestService:
    RedSettings()
    pool = get_pool()
    storage = UploadStorage(store=red_deps.UPLOADS_STORE, pool=pool)
    return ManualIngestService(pool=pool, storage=storage)
