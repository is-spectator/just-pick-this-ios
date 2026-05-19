from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


AppEnv = Literal["development", "test", "staging", "production"]
PipiCardComposer = Literal["deterministic", "deepseek"]
WebSearchProvider = Literal["disabled", "tavily"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    app_name: str = Field(default="just-pick-this-backend", validation_alias="APP_NAME")
    app_version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    app_env: AppEnv = Field(default="development", validation_alias="APP_ENV")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    api_v1_prefix: str = Field(default="/v1", validation_alias="API_V1_PREFIX")
    database_url: PostgresDsn | None = Field(default=None, validation_alias="DATABASE_URL")
    pipi_card_composer: PipiCardComposer = Field(
        default="deterministic",
        validation_alias="PIPI_CARD_COMPOSER",
    )
    deepseek_api_key: SecretStr | None = Field(default=None, validation_alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", validation_alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-reasoner", validation_alias="DEEPSEEK_MODEL")
    deepseek_timeout_seconds: float = Field(default=20.0, validation_alias="DEEPSEEK_TIMEOUT_SECONDS")
    web_search_provider: WebSearchProvider = Field(default="disabled", validation_alias="WEB_SEARCH_PROVIDER")
    tavily_api_key: SecretStr | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    tavily_search_max_results: int = Field(default=5, validation_alias="TAVILY_SEARCH_MAX_RESULTS")
    tavily_image_max_results: int = Field(default=8, validation_alias="TAVILY_IMAGE_MAX_RESULTS")
    tavily_timeout_seconds: float = Field(default=8.0, validation_alias="TAVILY_TIMEOUT_SECONDS")
    web_search_timeout_seconds: float = Field(default=8.0, validation_alias="WEB_SEARCH_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
