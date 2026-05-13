"""GET /monitor — Plant Monitor hub page."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from wp6_data.shared import render_page

router = APIRouter()

PAGE_TITLE = "SPoHF Blue - Plant Monitor"

_EXTRA_CSS = """
    .grid { display: grid; gap: 20px;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
    .grid article { margin-bottom: 0; }
    .grid article h3 { margin-top: 0; }
    .btn { display: inline-block; padding: 8px 16px;
           background: var(--pico-primary-background);
           color: var(--pico-primary-inverse);
           text-decoration: none; border-radius: 4px; }
    .btn:hover { opacity: 0.85; text-decoration: none; }
"""


@router.get("/", response_class=HTMLResponse)
async def monitor_home() -> str:
    """Plant Monitor hub — links to GDD, soil, light, and microclimate views."""
    content = """
        <h1>Plant Monitor</h1>
        <p>Agronomic analytics for the SPoHF blueberry farm.</p>

        <div class="grid">
            <article>
                <h3>GDD Tracker</h3>
                <p>Cumulative Growing Degree Days from biofix.
                   Year-over-year comparison with harvest threshold
                   annotations.</p>
                <a href="/monitor/gdd" class="btn">View GDD</a>
            </article>

            <article>
                <h3>Soil Conditions</h3>
                <p>Soil temperature, moisture, pH, and electrical
                   conductivity across all soil sensors.</p>
                <a href="/monitor/soil" class="btn">View Soil</a>
            </article>

            <article>
                <h3>Light</h3>
                <p>Photosynthetically Active Radiation (PAR) from
                   in-canopy sensors, plus outdoor solar radiation
                   from the weather station.</p>
                <a href="/monitor/light" class="btn">View Light</a>
            </article>

            <article>
                <h3>Microclimate</h3>
                <p>Air temperature, humidity, and leaf wetness
                   sensors across the farm.</p>
                <a href="/monitor/microclimate" class="btn">View Microclimate</a>
            </article>

            <article>
                <h3>Sensor Correlations</h3>
                <p>Pearson / Spearman / Kendall correlation matrix
                   across all sensor types. Reveals co-movement
                   between climate, soil, and light.</p>
                <a href="/monitor/correlation" class="btn">View Correlations</a>
            </article>
        </div>
    """
    return render_page(PAGE_TITLE, content, show_back_link=True,
                       extra_css=_EXTRA_CSS)
