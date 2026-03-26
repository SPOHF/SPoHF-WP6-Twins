"""Red dashboard bookmark page."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_dashboard_page
from wp6_data.shared.auth import verify_session_user

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page() -> str:
    """Dashboard page showing saved chart bookmarks."""
    return render_dashboard_page("SPoHF Red")
