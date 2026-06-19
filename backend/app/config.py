from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AppEnv = Literal["development", "test", "staging", "production"]
PipiCardComposer = Literal["deterministic", "openai"]
PipiModelProvider = Literal["deterministic", "openai"]
LlmProvider = Literal["none", "mock_shadow", "mock_shadow_schema_error", "openai"]
WebSearchProvider = Literal["disabled", "tavily"]
EmailProvider = Literal["console", "smtp"]
AmapRouteMode = Literal["walking", "driving", "transit", "bicycling"]
LangGraphCheckpointBackend = Literal["memory", "postgres", "disabled"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    app_name: str = Field(default="just-pick-this-backend", validation_alias="APP_NAME")
    app_version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    app_env: AppEnv = Field(default="development", validation_alias="APP_ENV")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    pipi_eval_mode: bool = Field(default=False, validation_alias="PIPI_EVAL_MODE")
    allow_eval_bypass: bool = Field(default=False, validation_alias="ALLOW_EVAL_BYPASS")
    auto_seed_on_request: bool = Field(default=False, validation_alias="AUTO_SEED_ON_REQUEST")
    enable_debug_routes: bool = Field(default=False, validation_alias="ENABLE_DEBUG_ROUTES")
    enable_admin_routes: bool = Field(default=True, validation_alias="ENABLE_ADMIN_ROUTES")
    allow_admin_mutate_runtime_tables: bool = Field(
        default=False,
        validation_alias="ALLOW_ADMIN_MUTATE_RUNTIME_TABLES",
    )
    langgraph_checkpoint_required: bool = Field(
        default=False,
        validation_alias="LANGGRAPH_CHECKPOINT_REQUIRED",
    )
    langgraph_checkpoint_backend: LangGraphCheckpointBackend = Field(
        default="disabled",
        validation_alias="LANGGRAPH_CHECKPOINT_BACKEND",
    )
    require_device_uid: bool = Field(default=True, validation_alias="REQUIRE_DEVICE_UID")
    api_v1_prefix: str = Field(default="/v1", validation_alias="API_V1_PREFIX")
    database_url: PostgresDsn | None = Field(default=None, validation_alias="DATABASE_URL")
    jwt_secret: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET")
    access_token_ttl_seconds: int = Field(default=86400, validation_alias="ACCESS_TOKEN_TTL_SECONDS")
    refresh_token_ttl_days: int = Field(default=30, validation_alias="REFRESH_TOKEN_TTL_DAYS")
    email_provider: EmailProvider = Field(default="console", validation_alias="EMAIL_PROVIDER")
    email_from_name: str = Field(default="皮皮", validation_alias="EMAIL_FROM_NAME")
    email_from_address: str | None = Field(default=None, validation_alias="EMAIL_FROM_ADDRESS")
    smtp_host: str | None = Field(default=None, validation_alias="SMTP_HOST")
    smtp_port: int | None = Field(default=None, validation_alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, validation_alias="SMTP_USERNAME")
    smtp_password: SecretStr | None = Field(default=None, validation_alias="SMTP_PASSWORD")
    smtp_use_ssl: bool = Field(default=True, validation_alias="SMTP_USE_SSL")
    smtp_use_starttls: bool = Field(default=False, validation_alias="SMTP_USE_STARTTLS")
    smtp_timeout_seconds: float = Field(default=10.0, validation_alias="SMTP_TIMEOUT_SECONDS")
    pipi_card_composer: PipiCardComposer = Field(
        default="deterministic",
        validation_alias="PIPI_CARD_COMPOSER",
    )
    pipi_model_provider: PipiModelProvider = Field(
        default="deterministic",
        validation_alias="PIPI_MODEL_PROVIDER",
    )
    llm_shadow_enabled: bool = Field(default=False, validation_alias="LLM_SHADOW_ENABLED")
    llm_rewrite_enabled: bool = Field(default=False, validation_alias="LLM_REWRITE_ENABLED")
    llm_rewrite_min_confidence: float = Field(default=0.78, validation_alias="LLM_REWRITE_MIN_CONFIDENCE")
    llm_provider: LlmProvider = Field(default="none", validation_alias="LLM_PROVIDER")
    llm_model: str = Field(default="none", validation_alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=10.0, validation_alias="LLM_TIMEOUT_SECONDS")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")
    openai_timeout_seconds: float = Field(default=20.0, validation_alias="OPENAI_TIMEOUT_SECONDS")
    web_search_provider: WebSearchProvider = Field(default="disabled", validation_alias="WEB_SEARCH_PROVIDER")
    tavily_api_key: SecretStr | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    tavily_search_max_results: int = Field(default=5, validation_alias="TAVILY_SEARCH_MAX_RESULTS")
    tavily_image_max_results: int = Field(default=8, validation_alias="TAVILY_IMAGE_MAX_RESULTS")
    tavily_timeout_seconds: float = Field(default=8.0, validation_alias="TAVILY_TIMEOUT_SECONDS")
    web_search_timeout_seconds: float = Field(default=8.0, validation_alias="WEB_SEARCH_TIMEOUT_SECONDS")
    amap_web_service_key: SecretStr | None = Field(default=None, validation_alias="AMAP_WEB_SERVICE_KEY")
    amap_search_radius_meters: int = Field(default=1200, validation_alias="AMAP_SEARCH_RADIUS_METERS")
    amap_search_limit: int = Field(default=20, validation_alias="AMAP_SEARCH_LIMIT")
    amap_route_mode_default: AmapRouteMode = Field(
        default="walking",
        validation_alias="AMAP_ROUTE_MODE_DEFAULT",
    )
    admin_token: SecretStr | None = Field(default=None, validation_alias="ADMIN_TOKEN")
    debug_dashboard_token: SecretStr | None = Field(
        default=None,
        validation_alias="DEBUG_DASHBOARD_TOKEN",
    )

    @field_validator(
        "openai_api_key",
        "tavily_api_key",
        "amap_web_service_key",
        "jwt_secret",
        "smtp_password",
        "admin_token",
        "debug_dashboard_token",
        mode="before",
    )
    @classmethod
    def blank_secret_as_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_production_guardrails(self) -> "Settings":
        if self.app_env not in {"production", "staging"}:
            return self
        errors: list[str] = []
        if self.admin_token is None:
            errors.append("ADMIN_TOKEN is required in production/staging")
        if self.database_url is None:
            errors.append("DATABASE_URL is required in production/staging")
        if self.allow_eval_bypass:
            errors.append("ALLOW_EVAL_BYPASS must be false in production/staging")
        if self.pipi_eval_mode:
            errors.append("PIPI_EVAL_MODE must be false in production/staging")
        if self.auto_seed_on_request:
            errors.append("AUTO_SEED_ON_REQUEST must be false in production/staging")
        if self.jwt_secret is None:
            errors.append("JWT_SECRET is required in production/staging")
        if self.email_provider == "console":
            errors.append("EMAIL_PROVIDER=console is forbidden in production/staging")
        if self.email_provider == "smtp":
            missing_smtp = [
                name
                for name, value in (
                    ("SMTP_HOST", self.smtp_host),
                    ("SMTP_PORT", self.smtp_port),
                    ("SMTP_USERNAME", self.smtp_username),
                    ("SMTP_PASSWORD", self.smtp_password),
                    ("EMAIL_FROM_ADDRESS", self.email_from_address),
                )
                if value is None or value == ""
            ]
            if missing_smtp:
                errors.append(f"missing SMTP config: {', '.join(missing_smtp)}")
        if self.llm_provider.startswith("mock_shadow"):
            errors.append("mock LLM providers are forbidden in production/staging")
        if self.enable_debug_routes and self.debug_dashboard_token is None:
            errors.append("DEBUG_DASHBOARD_TOKEN is required when debug routes are enabled")
        if self.langgraph_checkpoint_required:
            errors.append("LANGGRAPH_CHECKPOINT_REQUIRED must be false in production/staging for V0")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
