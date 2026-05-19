"""Request and response schemas for the Pipi chat API surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.schemas.cards import CardSummary, HelpCardSummary, LightEvent


class ApiModel(BaseModel):
    """Base schema that allows forward-compatible metadata from clients/services."""

    model_config = ConfigDict(extra="allow")


class BootstrapRequest(ApiModel):
    user_id: str | None = None
    device_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("device_id", "device_uid"),
    )
    platform: str | None = None
    app_version: str | None = None
    locale: str | None = None
    timezone: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BootstrapResponse(ApiModel):
    conversation_id: str
    user_id: str | None = None
    help_feed: list[HelpCardSummary] = Field(default_factory=list)
    light_events: list[LightEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatTurnRequest(ApiModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    device_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("device_id", "device_uid"),
    )
    user_id: str | None = None
    client_turn_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallView(ApiModel):
    id: str | None = None
    name: str
    status: Literal["skipped", "unavailable", "succeeded", "failed", "pending"] | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ChatTurnResponse(ApiModel):
    conversation_id: str
    user_turn_id: str | None = None
    assistant_turn_id: str | None = None
    assistant_message: str | None = None
    cards: list[CardSummary] = Field(default_factory=list)
    help_cards: list[HelpCardSummary] = Field(default_factory=list)
    light_events: list[LightEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
