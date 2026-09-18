from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ROUTEMIND_", extra="ignore")

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    secret_key: SecretStr = SecretStr("development-only-change-me-at-least-32-chars")
    database_path: str = "routemind.db"
    environment: str = "development"
    secure_cookies: bool = False
    catalog_ttl_seconds: int = 900
    request_timeout_seconds: float = 120.0
    default_output_tokens: int = 1024
    catalog_max_stale_seconds: int = 3600
    rate_limit_per_minute: int = 60
    max_fallback_attempts: int = 2
    app_url: str | None = None
    app_name: str = "RouteMind"

@lru_cache
def get_settings() -> Settings:
    return Settings()
