"""Shared dashboard bookmark page."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_dashboard_page
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
) -> str:
    """Dashboard page showing saved chart bookmarks."""
    return render_dashboard_page(
        config.title, data_source=provider.data_source_label,
    )
