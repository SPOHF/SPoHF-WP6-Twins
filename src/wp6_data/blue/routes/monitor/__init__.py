"""Blue Plant Monitor — GDD, soil conditions, light, and microclimate pages."""

from fastapi import APIRouter, Depends

from wp6_data.blue.routes.monitor import gdd, home, light, microclimate, soil
from wp6_data.shared.auth import verify_session_user

router = APIRouter(prefix="/monitor", dependencies=[Depends(verify_session_user)])
router.include_router(home.router)
router.include_router(gdd.router)
router.include_router(soil.router)
router.include_router(light.router)
router.include_router(microclimate.router)
