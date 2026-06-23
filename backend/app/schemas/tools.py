from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


ToolName = Literal[
    "search_knowledge",
    "create_recommendation_card",
    "draft_help_card",
    "update_help_card",
    "publish_help_card",
    "submit_one_liner_answer",
    "finalize_help_card",
    "save_intent_answer",
    "light_user",
    "amap_geocode",
    "amap_reverse_geocode",
    "amap_poi_search",
    "amap_route_plan",
    "build_amap_uri",
]

ToolCallStatus = Literal["running", "succeeded", "failed"]
KnowledgeHitType = Literal["image_asset", "help_answer", "knowledge_fact", "intent_answer", "web_result"]


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class ToolCallRecord(ToolSchema):
    id: str
    tool_name: ToolName
    status: ToolCallStatus
    input_json: dict[str, Any]
    output_json: dict[str, Any] | None = None
    error_message: str | None = None
    agent_run_id: str | None = None
    question_id: str | None = None
    help_request_id: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class KnowledgeHit(ToolSchema):
    id: str
    hit_type: KnowledgeHitType
    title: str
    text: str
    score: float = Field(ge=0, le=1)
    source_id: str | None = None
    image_asset_id: str | None = None
    evidence_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchKnowledgeInput(ToolSchema):
    query: str = Field(min_length=1, max_length=1000)
    question_id: str | None = None
    user_id: str | None = None
    limit: int = Field(default=8, ge=1, le=20)
    allow_web: bool = True
    allow_images: bool = True


class SearchKnowledgeOutput(ToolSchema):
    query: str
    retrieval_run_id: str | None = None
    hits: list[KnowledgeHit]


class AmapGeocodeInput(ToolSchema):
    address: str = Field(min_length=1, max_length=500)
    city: str | None = Field(default=None, max_length=100)


class AmapGeocodeOutput(ToolSchema):
    formatted_address: str | None = None
    lng: float | None = None
    lat: float | None = None
    adcode: str | None = None
    city: str | None = None


class AmapReverseGeocodeInput(ToolSchema):
    lng: float
    lat: float


class AmapReverseGeocodeOutput(ToolSchema):
    formatted_address: str | None = None
    city: str | None = None
    district: str | None = None
    township: str | None = None
    pois: list[dict[str, Any]] = Field(default_factory=list)


class AmapPoiCandidateSchema(ToolSchema):
    poi_id: str | None = None
    name: str
    type: str | None = None
    typecode: str | None = None
    address: str | None = None
    lng: float | None = None
    lat: float | None = None
    distance_meters: int | None = None
    tel: str | None = None


class AmapPoiSearchInput(ToolSchema):
    city: str | None = Field(default=None, max_length=100)
    keyword: str = Field(min_length=1, max_length=120)
    types: str | None = Field(default=None, max_length=255)
    center_lng: float | None = None
    center_lat: float | None = None
    radius_meters: int | None = Field(default=None, ge=1, le=50000)
    limit: int | None = Field(default=None, ge=1, le=50)


class AmapPoiSearchOutput(ToolSchema):
    search_run_id: str | None = None
    status: str = "succeeded"
    candidates: list[AmapPoiCandidateSchema] = Field(default_factory=list)
    disabled: bool = False
    error_message: str | None = None


class AmapRoutePlanInput(ToolSchema):
    origin_lng: float
    origin_lat: float
    destination_lng: float
    destination_lat: float
    mode: Literal["walking", "driving", "transit", "bicycling"] = "walking"


class AmapRoutePlanOutput(ToolSchema):
    route_run_id: str | None = None
    status: str = "succeeded"
    distance_meters: int | None = None
    duration_seconds: int | None = None
    summary_text: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)
    disabled: bool = False
    error_message: str | None = None


class BuildAmapUriInput(ToolSchema):
    target_name: str = Field(min_length=1, max_length=120)
    target_lng: float
    target_lat: float
    origin_lng: float | None = None
    origin_lat: float | None = None
    mode: Literal["walking", "driving", "transit", "bicycling"] = "walking"


class BuildAmapUriOutput(ToolSchema):
    uri: str
    label: str = "高德导航"


class RecommendationCardItem(ToolSchema):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=240)
    category: str | None = Field(default=None, max_length=80)


class RecommendationDecisionFactor(ToolSchema):
    text: str = Field(min_length=1, max_length=1200)
    key: str | None = Field(default=None, max_length=80)


class CreateRecommendationCardInput(ToolSchema):
    question_id: str | None = Field(default=None, min_length=1)
    help_card_id: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    user_id: str | None = Field(default=None, min_length=1)
    intent_answer_id: str | None = None
    item: RecommendationCardItem
    decision_factor: RecommendationDecisionFactor
    image_asset_id: str | None = Field(default=None, min_length=1)
    image_required: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    retrieval_run_id: str | None = Field(default=None, min_length=1)
    confidence: float = Field(ge=0.7, le=1)
    source: str = Field(default="pipi_tool", min_length=1, max_length=40)
    status: str = Field(default="active", min_length=1, max_length=40)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_card_shape(cls, data: object) -> object:
        """Accept pre-V0 callers while storing only item + decision factor."""

        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        legacy_title = normalized.pop("title", None)
        legacy_reason = normalized.pop("reason", None)
        legacy_subtitle = normalized.pop("subtitle", None)
        legacy_category = normalized.pop("category", None)
        normalized.pop("bullets", None)
        normalized.pop("followups", None)
        normalized.pop("reasons", None)
        normalized.pop("warning", None)

        if "item" not in normalized and legacy_title:
            normalized["item"] = {
                "title": legacy_title,
                "subtitle": legacy_subtitle,
                "category": legacy_category,
            }
        elif isinstance(normalized.get("item"), dict):
            item = dict(normalized["item"])
            if legacy_subtitle is not None and item.get("subtitle") is None:
                item["subtitle"] = legacy_subtitle
            if legacy_category is not None and item.get("category") is None:
                item["category"] = legacy_category
            normalized["item"] = item
        elif isinstance(normalized.get("item"), str):
            normalized["item"] = {"title": normalized["item"]}

        if "decision_factor" not in normalized:
            decision_text = legacy_reason or legacy_subtitle
            if decision_text:
                normalized["decision_factor"] = {"text": decision_text}
        elif isinstance(normalized.get("decision_factor"), str):
            normalized["decision_factor"] = {"text": normalized["decision_factor"]}

        return normalized

    @field_validator("evidence_ids")
    @classmethod
    def reject_blank_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("items must not be blank")
        return value

    @model_validator(mode="after")
    def require_question_or_help_card(self) -> CreateRecommendationCardInput:
        if self.question_id is None and self.help_card_id is None:
            raise ValueError("question_id or help_card_id is required")
        return self


class RecommendationCardOutput(ToolSchema):
    card_id: str
    question_id: str
    user_id: str
    item: RecommendationCardItem
    decision_factor: RecommendationDecisionFactor
    image_asset_id: str | None = None
    image_required: bool = False
    image_status: str
    evidence_ids: list[str]
    confidence: float
    status: str


class DraftHelpCardInput(ToolSchema):
    question_id: str = Field(min_length=1)
    owner_user_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    context: str = Field(
        min_length=1,
        max_length=1200,
        validation_alias=AliasChoices("context", "context_text"),
    )
    wants: list[str] = Field(default_factory=list, max_length=20)
    avoids: list[str] = Field(default_factory=list, max_length=20)
    constraints: dict[str, Any] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)
    reward: dict[str, Any] | None = None
    answer_stats: dict[str, Any] = Field(default_factory=dict)
    min_answers_required: int = Field(default=3, ge=1, le=20)

    @property
    def context_text(self) -> str:
        return self.context


class HelpCardOutput(ToolSchema):
    help_card_id: str
    question_id: str
    owner_user_id: str
    title: str
    context: str = Field(validation_alias=AliasChoices("context", "context_text"))
    wants: list[str] = Field(default_factory=list, max_length=20)
    avoids: list[str] = Field(default_factory=list, max_length=20)
    constraints: dict[str, Any] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)
    reward: dict[str, Any] | None = None
    answer_stats: dict[str, Any] = Field(default_factory=dict)
    status: str
    answer_count: int = 0
    min_answers_required: int
    published_at: datetime | None = None

    @property
    def context_text(self) -> str:
        return self.context


class UpdateHelpCardInput(ToolSchema):
    help_card_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    owner_user_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    context: str | None = Field(
        default=None,
        min_length=1,
        max_length=1200,
        validation_alias=AliasChoices("context", "context_text"),
    )
    wants: list[str] | None = Field(default=None, max_length=20)
    avoids: list[str] | None = Field(default=None, max_length=20)
    constraints: dict[str, Any] | None = None
    revision: int | None = Field(default=None, ge=1)
    reward: dict[str, Any] | None = None
    min_answers_required: int | None = Field(default=None, ge=1, le=20)

    @property
    def context_text(self) -> str | None:
        return self.context

    @model_validator(mode="after")
    def require_update(self) -> UpdateHelpCardInput:
        if (
            self.title is None
            and self.context is None
            and self.wants is None
            and self.avoids is None
            and self.constraints is None
            and self.revision is None
            and self.reward is None
            and self.min_answers_required is None
        ):
            raise ValueError("at least one help card field must be updated")
        return self


class PublishHelpCardInput(ToolSchema):
    help_card_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    owner_user_id: str | None = None


class SubmitOneLinerAnswerInput(ToolSchema):
    help_card_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    answer_user_id: str = Field(min_length=1)
    raw_text: str = Field(min_length=1, max_length=400)
    normalized_text: str | None = Field(default=None, max_length=400)


class SubmitOneLinerAnswerOutput(ToolSchema):
    help_answer_id: str
    help_card_id: str
    answer_user_id: str
    raw_text: str
    normalized_text: str | None = None
    status: str
    reward_status: str
    answer_count: int
    finalization_ready: bool


class SaveIntentAnswerInput(ToolSchema):
    help_card_id: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    question_id: str | None = Field(default=None, min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    intent_id: str | None = Field(default=None, min_length=1)
    intent_key: str = Field(default="pipi_help_finalized", min_length=1, max_length=255)
    intent_name: str = Field(default="Pipi finalized help answer", min_length=1, max_length=255)
    answer_text: str = Field(min_length=1, max_length=2000)
    image_asset_id: str | None = Field(default=None, min_length=1)
    locale: str | None = Field(default="zh-CN", max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=20)
    evidence_answer_ids: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=50, ge=0, le=1000)
    is_active: bool = True

    @field_validator("tags", "evidence_answer_ids")
    @classmethod
    def reject_blank_list_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("items must not be blank")
        return value


class SaveIntentAnswerOutput(ToolSchema):
    intent_answer_id: str
    intent_id: str
    help_card_id: str | None = None
    question_id: str | None = None
    answer_text: str
    status: str
    evidence_answer_ids: list[str]


class LightUserInput(ToolSchema):
    user_id: str = Field(min_length=1)
    conversation_id: str | None = None
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=400)
    type: str = Field(default="pipi_update", min_length=1, max_length=60)
    target_type: str | None = Field(default=None, max_length=60)
    target_id: str | None = Field(default=None, min_length=1)
    question_id: str | None = None
    help_card_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    recommendation_card_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("recommendation_card_id", "card_id"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def map_target_id(self) -> LightUserInput:
        if self.target_type == "card" and self.target_id and self.recommendation_card_id is None:
            self.recommendation_card_id = self.target_id
        if self.target_type == "help_card" and self.target_id and self.help_card_id is None:
            self.help_card_id = self.target_id
        return self


class LightUserOutput(ToolSchema):
    light_event_id: str
    user_id: str
    type: str
    title: str
    body: str
    lit_at: datetime
    expires_at: datetime | None = None


ToolInput = (
    SearchKnowledgeInput
    | CreateRecommendationCardInput
    | DraftHelpCardInput
    | UpdateHelpCardInput
    | PublishHelpCardInput
    | SubmitOneLinerAnswerInput
    | SaveIntentAnswerInput
    | LightUserInput
)

ToolOutput = (
    SearchKnowledgeOutput
    | RecommendationCardOutput
    | HelpCardOutput
    | SubmitOneLinerAnswerOutput
    | SaveIntentAnswerOutput
    | LightUserOutput
)
