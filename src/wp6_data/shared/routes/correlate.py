"""Shared correlation matrix page route."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_correlation_page, resolve_date_range
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/correlate", response_class=HTMLResponse)
async def correlation_page(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> str:
    """Sensor correlation matrix page with interactive heatmap."""
    start, end, _, _ = resolve_date_range(start, end)
    return render_correlation_page(
        config.title, start, end, data_source=provider.data_source_label,
    )
