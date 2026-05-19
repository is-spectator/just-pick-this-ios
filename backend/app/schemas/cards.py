"""Card, help-feed, and light-event schemas for the API boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base schema that allows forward-compatible fields from service results."""

    model_config = ConfigDict(extra="allow")


class ImageAsset(ApiModel):
    id: str
    url: str
    source_url: str | None = None
    source_domain: str | None = None
    caption: str | None = None
    alt_text: str | None = None
    verified: bool
    is_ai_generated: bool
    source_type: str | None = None
    license_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CardSummary(ApiModel):
    id: str
    title: str
    subtitle: str | None = None
    one_liner: str | None = None
    bullets: list[str] = Field(default_factory=list)
    warning: str | None = None
    followups: list[str] = Field(default_factory=list)
    status: str | None = None
    image: ImageAsset | None = None
    image_status: Literal["attached", "missing", "candidate_rejected"] | str = "missing"
    image_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CardDetail(CardSummary):
    description: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HelpCardSummary(ApiModel):
    id: str
    prompt: str
    status: Literal["open", "answered", "closed"] | str = "open"
    one_liner: str | None = None
    card: CardSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class HelpFeedResponse(ApiModel):
    items: list[HelpCardSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class HelpCardOneLinerRequest(ApiModel):
    text: str = Field(min_length=1)
    user_id: str | None = None
    device_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HelpCardOneLinerResponse(ApiModel):
    help_card_id: str
    answer_id: str | None = None
    accepted: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class LightEvent(ApiModel):
    id: str
    kind: str
    title: str | None = None
    message: str | None = None
    card_id: str | None = None
    help_card_id: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LightEventsResponse(ApiModel):
    items: list[LightEvent] = Field(default_factory=list)
    next_cursor: str | None = None


class CardAcceptRequest(ApiModel):
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CardAcceptResponse(ApiModel):
    card_id: str
    accepted: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
