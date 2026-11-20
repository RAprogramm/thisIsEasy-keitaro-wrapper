"""Environment-driven application settings loaded from .env."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: SecretStr = SecretStr("")
    keitaro_timeout: float = 30.0
    database_url: str = "postgresql+psycopg:///keitaro"
    # Task name prefix: test_surname_
    campaign_prefix: str = ""
    # Where the first stream (geo -> Google) redirects to
    google_url: str = "https://www.google.com"
    # Lifetime of the cached /api/dictionaries response, in seconds.
    dictionaries_ttl: float = 60.0
    # SQLAlchemy connection pool tuning.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    # Logging verbosity: DEBUG, INFO, WARNING, ERROR.
    log_level: str = "INFO"
    # Log format: "text" or "json".
    log_format: str = "text"
    # Comma-separated list of allowed CORS origins (empty disables CORS).
    cors_origins: str = ""
    # Max requests per minute per client IP for mutating endpoints.
    rate_limit_per_minute: int = 120


settings = Settings()
