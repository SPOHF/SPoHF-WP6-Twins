"""WP6 Grey Digital Twin — demo / proof-of-concept.

A minimal twin that runs entirely in-memory with generated sensor data.
Demonstrates the platform: provider + metadata + this file = full dashboard.
"""

from pathlib import Path

from wp6_data.grey.provider import GreySensorProvider
from wp6_data.shared import render_card
from wp6_data.shared.app_factory import create_app
from wp6_data.shared.metadata import MetadataRegistry
from wp6_data.shared.provider import TwinConfig


def _herb_card() -> str:
    return render_card(
        "Herb Garden",
        "<p>This is a demo twin with synthetic sensor data. "
        "No database needed &mdash; data is generated in-memory.</p>",
        card_class="card-bg card-bg-status",
    )


config = TwinConfig(
    twin_id="grey",
    title="SPoHF Grey Digital Twin (Demo)",
    provider=GreySensorProvider(),
    metadata=MetadataRegistry(Path(__file__).parent / "metadata.yaml"),
    export_dir=Path("/tmp/wp6-grey-exports"),
    hero_cards=[_herb_card],
    require_auth=False,
)

app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
