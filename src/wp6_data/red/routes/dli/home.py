"""GET /dli — DLI dashboard overview page."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import get_model
from wp6_data.shared import render_page

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def dli_home(user: str = Depends(deps.verify_auth)) -> str:
    """DLI dashboard overview page."""
    if not deps.db:
        return render_page("DLI - WP6 Red", "<h1>Database not connected</h1>", show_back_link=True)

    # Get model status for the card
    model = get_model()
    user_is_admin = deps.is_admin(user)

    # Build model card based on status and permissions
    if model.is_trained() and model.stats:
        trained_date = model.stats.training_date.strftime("%Y-%m-%d")
        r2 = model.stats.r2_score
        model_status = f"""
            <p class="success">Trained: {trained_date}</p>
            <small>R² = {r2:.3f}</small>
        """
    else:
        model_status = "<small>Not trained</small>"

    if user_is_admin:
        model_card = f"""
            <article>
                <h3>Prediction Model</h3>
                <p>Train ML model to predict indoor PAR from weather data.</p>
                {model_status}
                <a href="/dli/model" class="btn">Manage Model</a>
            </article>
        """
    else:
        model_card = f"""
            <article class="card-disabled">
                <h3>Prediction Model</h3>
                <p>ML model to predict indoor PAR from weather data.</p>
                {model_status}
                <span class="btn-disabled">Admin only</span>
            </article>
        """

    extra_css = """
        .grid { display: grid; gap: 20px;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
        .grid article { margin-bottom: 0; }
        .grid article h3 { margin-top: 0; }
        .card-primary { border: 2px solid var(--pico-primary-background); }
        .card-disabled { opacity: 0.6; }
        .btn { display: inline-block; padding: 8px 16px; background: var(--pico-primary-background);
               color: var(--pico-primary-inverse); text-decoration: none; border-radius: 4px;
               margin-right: 8px; }
        .btn:hover { opacity: 0.85; text-decoration: none; }
        .btn-disabled { display: inline-block; padding: 8px 16px; background: #ccc;
                       color: #666; border-radius: 4px; font-size: 0.9em; }
    """

    content = f"""
        <h1>DLI Dashboard</h1>
        <p>Daily Light Integral analysis for PAR sensors.</p>

        <div class="grid">
            <article>
                <h3>PAR Chart</h3>
                <p>Raw PAR readings: light above lamps vs under lamps.</p>
                <a href="/dli/chart" class="btn">View Chart</a>
            </article>

            <article>
                <h3>History</h3>
                <p>Compare natural light vs total light (with lamps) over time.</p>
                <a href="/dli/history" class="btn">View History</a>
            </article>

            <article class="card-primary">
                <h3>Forecast</h3>
                <p>Predict plant light based on schedule and weather data.</p>
                <a href="/dli/forecast" class="btn">View Forecast</a>
            </article>

            <article>
                <h3>Performance</h3>
                <p>Compare model predictions with actual sensor readings over time.</p>
                <a href="/dli/performance" class="btn">View Performance</a>
            </article>

            {model_card}
        </div>
    """

    return render_page("DLI Dashboard - WP6 Red", content, extra_css=extra_css, show_back_link=True)
