"""GET /monitor — Plant Monitor hub page."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_hub_card, render_hub_grid, render_page

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Plant Monitor"


@router.get("/", response_class=HTMLResponse)
async def monitor_home() -> str:
    """Plant Monitor hub — links to GDD, soil, light, and microclimate views."""
    content = f"""
        <h1>Plant Monitor</h1>
        <p>Agronomic analytics for the SPoHF blueberry farm.</p>

        {render_hub_grid([
            render_hub_card(
                "GDD Tracker",
                "Cumulative Growing Degree Days from biofix. Year-over-year "
                "comparison with harvest threshold annotations.",
                href="/monitor/gdd", label="View GDD",
            ),
            render_hub_card(
                "Soil Conditions",
                "Soil temperature, moisture, pH, and electrical conductivity "
                "across all soil sensors.",
                href="/monitor/soil", label="View Soil",
            ),
            render_hub_card(
                "Light",
                "Photosynthetically Active Radiation (PAR) from in-canopy sensors, "
                "plus outdoor solar radiation from the weather station.",
                href="/monitor/light", label="View Light",
            ),
            render_hub_card(
                "Microclimate",
                "Air temperature, humidity, and leaf wetness sensors across the farm.",
                href="/monitor/microclimate", label="View Microclimate",
            ),
        ])}
    """
    return render_page(PAGE_TITLE, content, show_back_link=True)
