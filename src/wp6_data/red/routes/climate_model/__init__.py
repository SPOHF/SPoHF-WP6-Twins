"""Red dashboard climate-model endpoints: status and train."""

from fastapi import APIRouter, Depends

from wp6_data.red.routes.climate_model import status, train
from wp6_data.shared.auth import verify_session_admin

router = APIRouter(
    prefix="/climate/model", dependencies=[Depends(verify_session_admin)]
)
router.include_router(status.router)
router.include_router(train.router)
