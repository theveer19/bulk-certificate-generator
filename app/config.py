"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file),
so the same image can run locally, in tests and in Docker without code
changes. See ``.env.example`` for the supported keys.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: .../bulk-certificate-generator
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bulk Certificate Generator"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # SQLite by default so the service runs with no external dependency.
    # Point this at PostgreSQL in production, e.g.
    #   postgresql+psycopg2://user:password@localhost:5432/certificates
    database_url: str = f"sqlite:///{(BASE_DIR / 'certificates.db').as_posix()}"

    # Where generated PDFs are written.
    storage_dir: Path = BASE_DIR / "storage" / "certificates"

    # Guard rail: refuse absurdly large payloads outright instead of
    # accepting a job we know we cannot process in reasonable time.
    max_recipients_per_job: int = 1000

    # Values printed on every certificate. Overridable per deployment.
    organization_name: str = "OneT Digital Solutions"
    signatory_name: str = "Veer Gurjar"
    signatory_title: str = "Director"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached so that configuration is parsed once per process; tests reset the
    cache via ``get_settings.cache_clear()`` when they need to.
    """
    return Settings()
