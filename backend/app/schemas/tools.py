from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


ToolName = Literal[
    "search_knowledge",
    "search_web_assets",
    "select_reference_image",
    "create_recommendation_card",
    "draft_help_card",
    "publish_help_card",
    "submit_one_liner_answer",
    "light_user",
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


class CreateRecommendationCardInput(ToolSchema):
    question_id: str | None = Field(default=None, min_length=1)
    user_id: str = Field(min_length=1)
    intent_answer_id: str | None = None
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=1200)
    bullets: list[str] = Field(min_length=1, max_length=4)
    image_asset_id: str | None = Field(default=None, min_length=1)
    image_required: bool = False
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.7, le=1)
    warning: str | None = Field(default=None, max_length=400)
    source: str = Field(default="pipi_tool", min_length=1, max_length=40)
    status: str = Field(default="active", min_length=1, max_length=40)

    @field_validator("bullets", "evidence_ids")
    @classmethod
    def reject_blank_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("items must not be blank")
        return value


class RecommendationCardOutput(ToolSchema):
    card_id: str
    question_id: str
    user_id: str
    title: str
    subtitle: str
    reason: str
    bullets: list[str]
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
    context_text: str = Field(min_length=1, max_length=1200)
    min_answers_required: int = Field(default=3, ge=1, le=20)


class HelpCardOutput(ToolSchema):
    help_card_id: str
    question_id: str
    owner_user_id: str
    title: str
    context_text: str
    status: str
    answer_count: int = 0
    min_answers_required: int
    published_at: datetime | None = None


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


class LightUserInput(ToolSchema):
    user_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=400)
    type: str = Field(default="pipi_update", min_length=1, max_length=60)
    question_id: str | None = None
    help_card_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    recommendation_card_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("recommendation_card_id", "card_id"),
    )
    expires_at: datetime | None = None


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
    | PublishHelpCardInput
    | SubmitOneLinerAnswerInput
    | LightUserInput
)

ToolOutput = (
    SearchKnowledgeOutput
    | RecommendationCardOutput
    | HelpCardOutput
    | SubmitOneLinerAnswerOutput
    | LightUserOutput
)
