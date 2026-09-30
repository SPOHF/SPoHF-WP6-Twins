"""Red dashboard dependencies: config, auth, globals, helpers."""

from pathlib import Path

from dotenv import load_dotenv

from wp6_data.config import ObjectStoreSettings, RedSettings, Settings
from wp6_data.red.db import MySQLConnection
from wp6_data.red.dli import OpenMeteoClient
from wp6_data.red.growth_sections import load_growth_sections
from wp6_data.shared.blob import make_store
from wp6_data.shared.export import get_export_metadata as _get_export_metadata
from wp6_data.shared.metadata import MetadataRegistry

load_dotenv()

base_settings = Settings()
settings = RedSettings()
_METADATA_PATH = Path(__file__).parent / "metadata.yaml"
metadata = MetadataRegistry(_METADATA_PATH)
# Red-only canopy zones over wire heights (CONTEXT "Growth section"); the shared
# metadata registry ignores this key, so it is loaded separately here.
growth_sections = load_growth_sections(_METADATA_PATH)

# MySQL connection settings
DB_HOST = settings.db_host
DB_PORT = settings.db_port
DB_NAME = settings.db_name
DB_USER = settings.db_user
DB_PASSWORD = settings.db_password

#: Red's corners of the shared bucket. One bucket serves every twin and every
#: artifact kind; prefixes are the separation (see issue 061).
EXPORT_PREFIX = "red/exports"
MODELS_PREFIX = "red/models"
UPLOADS_PREFIX = "red/manual-uploads"

_object_store = ObjectStoreSettings()

EXPORT_STORE = make_store(_object_store, prefix=EXPORT_PREFIX)

#: Trained models (DLI + the climate chain). Separate prefix from exports, not
#: because the store cares, but because exports are regenerated nightly and
#: cleared wholesale first — a models artifact swept up by that would be a very
#: confusing outage.
MODELS_STORE = make_store(_object_store, prefix=MODELS_PREFIX)

#: Keys within MODELS_STORE. Named here rather than in each model module so the
#: layout of red's prefix is visible in one place.
DLI_MODEL_KEY = "light_model.pkl"
CLIMATE_MODEL_KEY = "climate_model.pkl"

#: Manually-uploaded source files (Sijia .xlsx and friends), content-addressed
#: at {source}/{sha256}{suffix}. The `manual_uploads` audit table is the system
#: of record; these are the files those rows point at.
UPLOADS_STORE = make_store(_object_store, prefix=UPLOADS_PREFIX)

# Database connection (managed via lifespan in dashboard.py)
db: MySQLConnection | None = None

# Weather client (shared across requests)
weather_client: OpenMeteoClient | None = None


def get_weather_client() -> OpenMeteoClient:
    """Get or create weather client."""
    global weather_client
    if weather_client is None:
        weather_client = OpenMeteoClient()
    return weather_client


def _export_info_html(export_meta: dict | None) -> str:
    """Generate HTML snippet showing export metadata."""
    if not export_meta:
        return "<small>CSV exports not yet available.</small>"
    return ""


async def get_export_metadata() -> dict | None:
    """Get metadata about available CSV exports."""
    return await _get_export_metadata(EXPORT_STORE)
