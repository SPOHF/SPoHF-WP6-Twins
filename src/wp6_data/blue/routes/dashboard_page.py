"""Blue dashboard bookmark page."""

from types import ModuleType
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.blue.datasource import GetActiveSource
from wp6_data.shared import render_dashboard_page
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    active_source: Annotated[tuple[ModuleType, str], GetActiveSource],
) -> str:
    """Dashboard page showing saved chart bookmarks."""
    _, source_name = active_source
    return render_dashboard_page("SPoHF Blue", data_source=source_name)
