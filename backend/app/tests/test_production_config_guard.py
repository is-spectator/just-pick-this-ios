from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


PROD_BASE = {
    "APP_ENV": "production",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/app",
    "ADMIN_TOKEN": "prod-admin-token",
    "PIPI_EVAL_MODE": "false",
    "ALLOW_EVAL_BYPASS": "false",
    "AUTO_SEED_ON_REQUEST": "false",
    "LLM_PROVIDER": "none",
    "JWT_SECRET": "prod-jwt-secret",
    "EMAIL_PROVIDER": "smtp",
    "EMAIL_FROM_ADDRESS": "noreply@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "465",
    "SMTP_USERNAME": "noreply@example.com",
    "SMTP_PASSWORD": "smtp-password",
}


def _settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **{**PROD_BASE, **overrides})


def test_production_missing_admin_token_fails() -> None:
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        _settings(ADMIN_TOKEN="")


def test_production_allow_eval_bypass_fails() -> None:
    with pytest.raises(ValidationError, match="ALLOW_EVAL_BYPASS"):
        _settings(ALLOW_EVAL_BYPASS="true")


def test_production_mock_shadow_provider_fails() -> None:
    with pytest.raises(ValidationError, match="mock LLM providers"):
        _settings(LLM_PROVIDER="mock_shadow")


def test_production_auto_seed_fails() -> None:
    with pytest.raises(ValidationError, match="AUTO_SEED_ON_REQUEST"):
        _settings(AUTO_SEED_ON_REQUEST="true")


def test_production_missing_jwt_secret_fails() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _settings(JWT_SECRET="")


def test_production_console_email_provider_fails() -> None:
    with pytest.raises(ValidationError, match="EMAIL_PROVIDER=console"):
        _settings(EMAIL_PROVIDER="console")


def test_production_missing_smtp_config_fails() -> None:
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        _settings(SMTP_HOST="")


def test_production_debug_enabled_requires_token() -> None:
    with pytest.raises(ValidationError, match="DEBUG_DASHBOARD_TOKEN"):
        _settings(ENABLE_DEBUG_ROUTES="true")


def test_development_can_start_with_relaxed_settings() -> None:
    settings = Settings(_env_file=None, APP_ENV="development", LLM_PROVIDER="mock_shadow")
    app = create_app(settings)
    assert app.title == settings.app_name


def test_production_checkpoint_required_is_not_supported_in_v0() -> None:
    with pytest.raises(ValidationError, match="LANGGRAPH_CHECKPOINT_REQUIRED must be false"):
        _settings(LANGGRAPH_CHECKPOINT_REQUIRED="true", LANGGRAPH_CHECKPOINT_BACKEND="postgres")


def test_staging_checkpoint_required_is_not_supported_in_v0() -> None:
    with pytest.raises(ValidationError, match="LANGGRAPH_CHECKPOINT_REQUIRED must be false"):
        _settings(APP_ENV="staging", LANGGRAPH_CHECKPOINT_REQUIRED="true", LANGGRAPH_CHECKPOINT_BACKEND="postgres")


def test_startup_guard_rejects_required_checkpoint_if_settings_are_constructed() -> None:
    settings = _settings(LANGGRAPH_CHECKPOINT_REQUIRED="false", LANGGRAPH_CHECKPOINT_BACKEND="postgres")
    object.__setattr__(settings, "langgraph_checkpoint_required", True)
    with pytest.raises(RuntimeError, match="LANGGRAPH_CHECKPOINT_REQUIRED must be false"):
        create_app(settings)
