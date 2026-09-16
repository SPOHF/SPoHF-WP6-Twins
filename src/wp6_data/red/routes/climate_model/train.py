"""POST /climate/model/train — refit the whole chain.

Always a full refit rather than an incremental update: the fits are cheap, the
record grows, and a chain assembled from stages trained at different moments
would report a quality none of its parts had.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from wp6_data.red import deps
from wp6_data.red.climate import data as climate_data
from wp6_data.red.climate.config import load_climate_model
from wp6_data.red.climate.training import train_chain
from wp6_data.shared import render_card, render_page

router = APIRouter()

PAGE_TITLE = "SPoHF Red - Train Climate Model"

# One retrain at a time. The fits are CPU-bound and the artifact is written
# whole, so two concurrent runs would race on the same file for no benefit.
_training_lock = asyncio.Lock()


def _error_page(message: str) -> str:
    return render_page(
        PAGE_TITLE,
        render_card("Training failed", f"<p>{message}</p>"),
        show_back_link=True, back_url="/climate/model/",
    )


@router.post("/train", response_model=None)
async def climate_model_train() -> HTMLResponse | RedirectResponse:
    """Retrain and redirect back to the status page (POST-redirect-GET)."""
    if not climate_data.is_connected():
        return HTMLResponse(_error_page("Database not connected."))
    if _training_lock.locked():
        return HTMLResponse(
            _error_page("A training run is already in progress. Try again shortly.")
        )

    async with _training_lock:
        try:
            config = load_climate_model(deps._METADATA_PATH)
            await train_chain(config, deps.get_weather_client())
        except Exception as error:  # noqa: BLE001 - surfaced to the admin as a card
            return HTMLResponse(_error_page(f"{type(error).__name__}: {error}"))

    return RedirectResponse("/climate/model/", status_code=303)
