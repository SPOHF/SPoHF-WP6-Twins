"""Shared dashboard home page with pluggable hero cards."""

import inspect
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from wp6_data.shared import (
    build_explore_tabs,
    render_card,
    render_explore_tabs,
    render_page,
)
from wp6_data.shared.auth import verify_session_user
from wp6_data.shared.export import get_export_metadata
from wp6_data.shared.routes.deps import get_provider, get_twin_config
from wp6_data.shared.twin import SensorDataProvider, TwinConfig

router = APIRouter(dependencies=[Depends(verify_session_user)])


@router.get("/", response_class=HTMLResponse)
async def home(
    config: Annotated[TwinConfig, Depends(get_twin_config)],
    provider: Annotated[SensorDataProvider, Depends(get_provider)],
    tab: str = "devices",
) -> str:
    """Dashboard home page — sensor explorer with pluggable hero cards."""
    device_data = await provider.fetch_device_data()
    manual_metadata = await provider.fetch_manual_metadata()

    export_meta = get_export_metadata(config.export_dir)
    available_exports = export_meta.get("devices", {}) if export_meta else {}

    explore_tabs = build_explore_tabs(
        config.metadata, device_data, available_exports,
        manual_metadata=manual_metadata,
    )

    # Render hero cards (can be sync or async callables)
    hero_html_parts = []
    for card_fn in config.hero_cards:
        result = card_fn()
        if inspect.isawaitable(result):
            result = await result
        hero_html_parts.append(result)
    hero_html = "\n".join(hero_html_parts)

    content = f"""
        <h1>{config.title}</h1>

        {render_card(
            "Dashboard",
            '<div style="display:flex;gap:0.5rem">'
            '<a href="/dashboard" role="button">My Dashboard</a>'
            '<a href="/chart" role="button" class="outline">'
            'New Chart</a></div>',
            description="Your bookmarked charts in one view. "
            "Or create a new chart from scratch.",
            card_class="card card-bg card-bg-chart",
        )}

        {hero_html}

        {render_card("Explore", render_explore_tabs(
            explore_tabs, active=tab, extra_tabs=config.explore_extra_tabs,
        ))}

        {config.home_extra_html}

        {render_card(
            "Status &amp; Coverage",
            '<a href="/status" role="button">View Status</a>',
            description="Data coverage timeline and sync status.",
            card_class="card-bg card-bg-status",
        )}
    """

    return render_page(config.title, content)
