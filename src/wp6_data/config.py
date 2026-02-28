"""Configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from WP6_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="WP6_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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
    sync_page_size: int = 1000
    sync_mode: str = "incremental"  # "full" or "incremental"
    sync_window_days: int = 1  # Days per window

    # Endpoints to sync (comma-separated)
    endpoints: str = "yookr-data"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"

    @property
    def endpoint_list(self) -> list[str]:
        """Parse endpoints string into list."""
        return [e.strip() for e in self.endpoints.split(",") if e.strip()]


class RedSettings(BaseSettings):
    """WP6 Red dashboard settings loaded from WP6_RED_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="WP6_RED_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "spohf2"
    db_user: str = "root"
    db_password: str = ""

    auth_users: str = ""
    admin_users: str = "admin"

    export_dir: str = "/data/exports"
