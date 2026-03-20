"""Red dashboard DLI endpoints: overview, history, forecast, performance."""

from fastapi import APIRouter, Depends

from wp6_data.red.routes.dli import chart, forecast, history, home, performance
from wp6_data.shared.auth import verify_session_user

router = APIRouter(prefix="/dli", dependencies=[Depends(verify_session_user)])
router.include_router(home.router)
router.include_router(chart.router)
router.include_router(history.router)
router.include_router(forecast.router)
router.include_router(performance.router)
