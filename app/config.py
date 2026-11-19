"""Environment-driven application settings loaded from .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""
    keitaro_timeout: float = 30.0
    database_url: str = "postgresql+psycopg:///keitaro"
    # Task name prefix: test_surname_
    campaign_prefix: str = "test_rozanov_"
    # Where the first stream (geo -> Google) redirects to
    google_url: str = "https://www.google.com"
    # Lifetime of the cached /api/dictionaries response, in seconds.
    dictionaries_ttl: float = 60.0
    # Logging verbosity: DEBUG, INFO, WARNING, ERROR.
    log_level: str = "INFO"


settings = Settings()
