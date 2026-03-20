"""Red dashboard DLI model endpoints: status, train, diagnostic."""

from fastapi import APIRouter, Depends

from wp6_data.red.routes.dli_model import diagnostic, status, train
from wp6_data.shared.auth import verify_session_admin

router = APIRouter(prefix="/dli/model", dependencies=[Depends(verify_session_admin)])
router.include_router(status.router)
router.include_router(train.router)
router.include_router(diagnostic.router)
