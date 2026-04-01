"""WP6 Blue Dashboard - TimescaleDB-backed sensor visualization."""

from pathlib import Path
from typing import Annotated

from fastapi import Cookie

from wp6_data.blue import deps
from wp6_data.blue.provider import BlueSensorProvider
from wp6_data.blue.routes import charts as blue_charts
from wp6_data.blue.routes import ops
from wp6_data.config import Settings
from wp6_data.shared import render_card
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.provider import TwinConfig

settings = Settings()


async def _startup() -> None:
    await deps.init_db(settings.tsdb_url)


async def _shutdown() -> None:
    await deps.close_db()


async def _get_provider_from_cookie(
    wp6_blue_source: Annotated[str | None, Cookie()] = None,
) -> BlueSensorProvider:
    """Per-request provider resolved from cookie."""
    return BlueSensorProvider(source_name=wp6_blue_source)


def _status_card() -> str:
    return render_card(
        "Status &amp; Coverage",
        '<a href="/status" role="button">View Status</a>',
        description="Sync status, data coverage timeline, "
        "and maintenance tools.",
        card_class="card-bg card-bg-status",
    )


config = TwinConfig(
    twin_id="blue",
    title="SPoHF Blue Digital Twin",
    provider=BlueSensorProvider(),
    metadata=deps.metadata,
    export_dir=Path(settings.blue_export_dir),
    extra_routers=[ops.router, blue_charts.router],
    hero_cards=[_status_card],
    provider_dependency=_get_provider_from_cookie,
    export_sanitise_names=True,
    lifespan_startup=_startup,
    lifespan_shutdown=_shutdown,
)

app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
