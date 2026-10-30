"""App settings. Everything comes from environment variables (or a local .env file)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "gemini": "gemini-2.5-flash",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ContextRelay"
    database_url: str = "sqlite:///./data/contextrelay.db"
    log_level: str = "INFO"
    log_dir: str = "logs"
    seed_on_startup: bool = True

    ai_provider: str = "none"  # anthropic | gemini | none
    ai_model: str = ""
    ai_api_key: str = ""
    ai_timeout_seconds: float = 20.0

    @property
    def resolved_model(self) -> str:
        return self.ai_model or DEFAULT_MODELS.get(self.ai_provider.lower(), "")

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider.lower() in DEFAULT_MODELS and bool(self.ai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
