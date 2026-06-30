"""Card, help-feed, and light-event schemas for the API boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    displayable: bool | None = None
    is_ai_generated: bool
    verification_status: str | None = None
    source_type: str | None = None
    license_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlaceLocation(ApiModel):
    lng: float
    lat: float
    coord_type: Literal["gcj02"] = "gcj02"


class PlacePayload(ApiModel):
    provider: Literal["amap"] | str
    poi_id: str | None = None
    name: str
    address: str | None = None
    location: PlaceLocation
    tel: str | None = None
    typecode: str | None = None


class RoutePayload(ApiModel):
    provider: Literal["amap"] | str
    mode: Literal["walking", "driving", "transit", "bicycling"] | str
    distance_meters: int | None = None
    duration_seconds: int | None = None
    summary_text: str | None = None
    route_run_id: str | None = None


class CardAction(ApiModel):
    type: Literal["open_amap"] | str
    label: str
    uri: str


class CardSummary(ApiModel):
    id: str
    type: str | None = None
    version: str | None = None
    target_type: Literal["restaurant", "ordering_bundle", "place"] | str | None = None
    title: str
    subtitle: str | None = None
    item: dict[str, Any] = Field(default_factory=dict)
    decision_factor: dict[str, Any] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)
    one_liner: str | None = None
    status: str | None = None
    image: ImageAsset | None = None
    place: PlacePayload | None = None
    route: RoutePayload | None = None
    action: CardAction | None = None
    image_status: Literal["attached", "missing", "candidate_rejected"] | str = "missing"
    image_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_minimal_card_contract(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        for forbidden in ("reasons", "bullets", "followups", "warning"):
            normalized.pop(forbidden, None)

        title = str(normalized.get("title") or "").strip()
        item = normalized.get("item")
        if item is None and title:
            normalized["item"] = {"title": title}
        elif isinstance(item, str):
            normalized["item"] = {"title": item}

        decision_factor = normalized.get("decision_factor")
        if isinstance(decision_factor, str):
            normalized["decision_factor"] = {"text": decision_factor}

        if not normalized.get("evidence_ids"):
            normalized["evidence_ids"] = _extract_evidence_ids(normalized)
        return normalized


class CardDetail(CardSummary):
    description: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HelpCardSummary(ApiModel):
    id: str
    prompt: str
    type: str | None = None
    version: str | None = None
    title: str | None = None
    location_state: Literal["in_area", "in_venue", "unknown"] | str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    wants: list[str] = Field(default_factory=list)
    avoids: list[str] = Field(default_factory=list)
    constraints: list[str] | dict[str, Any] = Field(default_factory=list)
    reward: dict[str, Any] = Field(default_factory=dict)
    answer_stats: dict[str, Any] = Field(default_factory=dict)
    revision: int | dict[str, Any] | None = None
    status: Literal["open", "answered", "closed"] | str = "open"
    context_text: str | None = None
    answer_count: int = 0
    one_liner: str | None = None
    card: CardSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class HelpFeedResponse(ApiModel):
    items: list[HelpCardSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class HelpAnswerSummary(ApiModel):
    id: str
    help_card_id: str
    raw_text: str
    status: str
    reward_status: str
    question_title: str
    question_context: str | None = None
    reward: dict[str, Any] = Field(default_factory=dict)
    final_recommendation_card_id: str | None = None
    settlement_reason: str | None = None
    used_as_final_evidence: bool = False
    created_at: datetime | None = None


class HelpAnswerListResponse(ApiModel):
    items: list[HelpAnswerSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class FavoriteChoiceSummary(ApiModel):
    id: str
    query: str
    status: str = "saved"
    help_request_id: str | None = None
    top_pick: dict[str, Any] | None = None
    created_at: datetime | None = None


class FavoriteChoiceListResponse(ApiModel):
    items: list[FavoriteChoiceSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class DrawerHistoryStateResponse(ApiModel):
    pinned_history_ids: list[str] = Field(default_factory=list)
    hidden_history_ids: list[str] = Field(default_factory=list)
    renamed_history_titles: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime | None = None


class HelpCardDetail(HelpCardSummary):
    pass


class HelpCardPublishRequest(ApiModel):
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HelpCardPublishResponse(ApiModel):
    help_card: dict[str, Any]
    ui_events: list[dict[str, Any]] = Field(default_factory=list)


class HelpCardOneLinerRequest(ApiModel):
    text: str = Field(min_length=1)
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HelpCardOneLinerResponse(ApiModel):
    help_card_id: str
    answer_id: str | None = None
    accepted: bool = True
    answer: dict[str, Any] | None = None
    help_card: dict[str, Any] | None = None
    reward: dict[str, Any] | None = None
    should_advance: bool = True
    toast: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HelpCardSkipRequest(ApiModel):
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HelpCardSkipResponse(ApiModel):
    ok: bool = True
    help_card_id: str
    event: dict[str, Any]


class HelpCardFinalAcceptRequest(ApiModel):
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HelpCardFinalAcceptResponse(ApiModel):
    help_card_id: str
    card_id: str
    accepted: bool = True
    feedback: dict[str, Any] = Field(default_factory=dict)
    event: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RewardsMeResponse(ApiModel):
    device_uid: str | None = None
    pending_value: int = 0
    granted_value: int = 0
    rejected_value: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)


class AnswererQualityResponse(ApiModel):
    user: dict[str, Any]
    quality: dict[str, Any]
    answers: dict[str, Any]
    rewards: dict[str, Any]
    moderation: dict[str, Any]
    behavior: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LightEvent(ApiModel):
    id: str
    kind: str
    type: str | None = None
    title: str | None = None
    message: str | None = None
    body: str | None = None
    card_id: str | None = None
    help_card_id: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LightEventsResponse(ApiModel):
    items: list[LightEvent] = Field(default_factory=list)
    events: list[LightEvent] = Field(default_factory=list)
    next_cursor: str | None = None


class CardAcceptRequest(ApiModel):
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CardAcceptResponse(ApiModel):
    card_id: str
    accepted: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CardFeedbackRequest(ApiModel):
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CardPostReviewRequest(CardFeedbackRequest):
    outcome: Literal["went_satisfied", "went_regretted", "not_went", "unknown"] | None = None
    went: bool | None = None
    satisfied: bool | None = None
    notes: str | None = None


class CardFeedbackResponse(ApiModel):
    card_id: str
    accepted: bool = False
    feedback: dict[str, Any] = Field(default_factory=dict)
    event: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserBehaviorEventRequest(ApiModel):
    event_type: str = Field(min_length=1)
    user_id: str | None = None
    device_id: str | None = None
    device_uid: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    card_id: str | None = None
    recommendation_card_id: str | None = None
    help_card_id: str | None = None
    help_answer_id: str | None = None
    source: str = "ios"
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserBehaviorEventResponse(ApiModel):
    event: dict[str, Any]
    accepted: bool = True


class UserPreferencesResponse(ApiModel):
    user_id: str
    device_uid: str
    preference_memory: dict[str, Any] = Field(default_factory=dict)


def _extract_evidence_ids(data: dict[str, Any]) -> list[str]:
    evidence_ids = _string_list(data.get("evidence_ids"))
    if evidence_ids:
        return evidence_ids

    provenance = data.get("provenance")
    if isinstance(provenance, dict):
        evidence_ids = _string_list(provenance.get("evidence_ids"))
        if evidence_ids:
            return evidence_ids

    evidence = data.get("evidence")
    if isinstance(evidence, list):
        extracted: list[str] = []
        for item in evidence:
            if isinstance(item, dict):
                value = item.get("id") or item.get("source_id")
            else:
                value = item
            text = str(value or "").strip()
            if text:
                extracted.append(text)
        return extracted
    return []


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [stripped for item in value if (stripped := str(item or "").strip())]
    return []
