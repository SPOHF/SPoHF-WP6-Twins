"""Red dashboard DLI endpoints: overview, history, forecast, performance."""

from fastapi import APIRouter

from wp6_data.red.routes.dli import chart, forecast, history, home, performance

router = APIRouter(prefix="/dli")
router.include_router(home.router)
router.include_router(chart.router)
router.include_router(history.router)
router.include_router(forecast.router)
router.include_router(performance.router)
