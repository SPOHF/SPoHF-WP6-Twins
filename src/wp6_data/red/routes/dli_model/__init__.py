"""Red dashboard DLI model endpoints: status, train, diagnostic."""

from fastapi import APIRouter, Depends

from wp6_data.red import deps
from wp6_data.red.routes.dli_model import diagnostic, status, train

router = APIRouter(prefix="/dli/model", dependencies=[Depends(deps.verify_admin_auth)])
router.include_router(status.router)
router.include_router(train.router)
router.include_router(diagnostic.router)
