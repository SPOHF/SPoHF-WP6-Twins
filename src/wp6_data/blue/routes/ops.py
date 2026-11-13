"""Blue dashboard operations endpoints: maintenance."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_card, render_page

router = APIRouter()


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance() -> str:
    """Hidden maintenance page for ops tools."""
    content = f"""
        <h1>Maintenance</h1>
        {render_card(
            "Metrics",
            '<p><a href="/metrics">Prometheus metrics</a></p>',
        )}
    """

    return render_page(
        "SPoHF Blue - Maintenance", content,
        show_back_link=True,
    )
