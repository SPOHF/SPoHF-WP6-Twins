"""WP6 Grey Digital Twin — demo / proof-of-concept.

A minimal twin that runs entirely in-memory with generated sensor data.
Demonstrates the platform: provider + metadata + this file = full dashboard.
"""

from pathlib import Path

from wp6_data.grey.provider import GreySensorProvider
from wp6_data.shared import render_card
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.twin import DataSource, ThemeColors, TwinConfig


def _herb_card() -> str:
    return render_card(
        "Herb Garden",
        "<p>This is a demo of the <strong>SPoHF WP6 Data Platform</strong> "
        "for digital twins. It uses synthetic sensor data generated "
        "in-memory &mdash; no database or hardware needed.</p>"
        '<p>Learn more about the project at '
        '<a href="https://spohf.github.io/SPoHF-WP6-Twins/" '
        'target="_blank">spohf.github.io/SPoHF-WP6-Twins</a>.</p>',
        card_class="card-bg card-bg-status",
    )


config = TwinConfig(
    twin_id="grey",
    title="SPoHF Grey Digital Twin (Demo)",
    data_sources=[
        DataSource(
            key="in-memory", label="Synthetic Data",
            provider=GreySensorProvider(),
        ),
    ],
    metadata=MetadataRegistry(Path(__file__).parent / "metadata.yaml"),
    export_dir=Path("/tmp/wp6-grey-exports"),
    theme=ThemeColors(
        primary="#6b7280", primary_light="#9ca3af", primary_dark="#4b5563",
        accent="#8b5cf6", surface_rgb="107, 114, 128",
    ),
    hero_cards=[_herb_card],
    require_auth=False,
)

app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    from wp6_data.shared.compat import run_async

    async def _serve() -> None:
        cfg = uvicorn.Config(app, host="0.0.0.0", port=8000)
        await uvicorn.Server(cfg).serve()

    run_async(_serve())
