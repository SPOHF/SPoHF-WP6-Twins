"""GET /dli — DLI dashboard overview page."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from wp6_data.red import deps
from wp6_data.red.dli import get_model
from wp6_data.shared import render_hub_card, render_hub_grid, render_page
from wp6_data.shared.auth import is_admin

router = APIRouter()

PAGE_TITLE = "SPoHF Red - DLI Dashboard"

@router.get("/", response_class=HTMLResponse)
async def dli_home(request: Request) -> str:
    """DLI dashboard overview page."""
    if not deps.db:
        return render_page(PAGE_TITLE, "<h1>Database not connected</h1>", show_back_link=True)

    # Get model status for the card
    model = get_model()
    user_is_admin = is_admin(request)

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
        model_card = render_hub_card(
            "Prediction Model",
            "Train ML model to predict indoor PAR from weather data.",
            body=model_status, href="/dli/model", label="Manage Model",
        )
    else:
        model_card = render_hub_card(
            "Prediction Model",
            "ML model to predict indoor PAR from weather data.",
            body=model_status, label="Admin only",
            disabled=True, card_class="card-disabled",
        )

    content = f"""
        <h1>DLI Dashboard</h1>
        <p>Daily Light Integral analysis for PAR sensors.</p>

        {render_hub_grid([
            render_hub_card(
                "PAR Chart", "Raw PAR readings: light above lamps vs under lamps.",
                href="/dli/chart", label="View Chart",
            ),
            render_hub_card(
                "History",
                "Compare natural light vs total light (with lamps) over time.",
                href="/dli/history", label="View History",
            ),
            render_hub_card(
                "Forecast", "Predict plant light based on schedule and weather data.",
                href="/dli/forecast", label="View Forecast", card_class="card-primary",
            ),
            render_hub_card(
                "Performance",
                "Compare model predictions with actual sensor readings over time.",
                href="/dli/performance", label="View Performance",
            ),
            model_card,
        ])}
    """

    return render_page(PAGE_TITLE, content, show_back_link=True)
