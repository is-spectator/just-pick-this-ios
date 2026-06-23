from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RequestCodeRequest(ApiModel):
    email: str
    device_uid: str | None = Field(
        default=None,
        validation_alias=AliasChoices("device_uid", "device_id"),
    )
    platform: str | None = None
    app_version: str | None = None


class RequestCodeResponse(ApiModel):
    ok: bool = True
    expires_in: int
    cooldown_seconds: int
    dev_code: str | None = None


class VerifyCodeRequest(ApiModel):
    email: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    device_uid: str | None = Field(
        default=None,
        validation_alias=AliasChoices("device_uid", "device_id"),
    )
    platform: str | None = None
    app_version: str | None = None


class AuthUser(ApiModel):
    id: str
    email: str | None = None
    display_name: str


class UpdateMeRequest(ApiModel):
    display_name: str = Field(min_length=1, max_length=32)


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class VerifyCodeResponse(ApiModel):
    user: AuthUser
    tokens: TokenPair


class RefreshRequest(ApiModel):
    refresh_token: str


class RefreshResponse(ApiModel):
    tokens: TokenPair


class LogoutRequest(ApiModel):
    refresh_token: str


class LogoutResponse(ApiModel):
    ok: bool = True


class MeResponse(ApiModel):
    user: AuthUser
    metadata: dict[str, Any] = Field(default_factory=dict)
