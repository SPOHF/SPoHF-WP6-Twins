"""Configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from WP6_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="WP6_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # SPoHF API
    api_base_url: str = "https://backoffice.spohf.com"
    api_token: str  # Required - bearer token

    # Neo4j Aura
    neo4j_uri: str  # bolt+s://xxx.databases.neo4j.io:7687
    neo4j_user: str = "neo4j"
    neo4j_password: str  # Required
    neo4j_database: str = "neo4j"

    # Sync behavior
    sync_lookback_hours: int = 24  # How far back on first run
    sync_page_size: int = 100
    sync_max_pages: int = 100  # Safety limit
    sync_mode: str = "auto"  # "auto", "windowed", or "incremental"
    sync_window_days: int = 1  # Days per window in windowed mode (use 30 for monthly)

    # Endpoints to sync (comma-separated)
    endpoints: str = "yookr-data"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"

    @property
    def endpoint_list(self) -> list[str]:
        """Parse endpoints string into list."""
        return [e.strip() for e in self.endpoints.split(",") if e.strip()]
