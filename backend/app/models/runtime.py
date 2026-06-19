from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_uid: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_provider: Mapped[str] = mapped_column(String(50), default="device", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(50))
    app_version: Mapped[str | None] = mapped_column(String(50))
    locale: Mapped[str | None] = mapped_column(String(50))
    timezone: Mapped[str | None] = mapped_column(String(100))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    conversations: Mapped[list[Conversation]] = relationship(back_populates="user")
    turns: Mapped[list[Turn]] = relationship(back_populates="user")
    questions: Mapped[list[Question]] = relationship(back_populates="user")
    recommendation_cards: Mapped[list[RecommendationCard]] = relationship(back_populates="user")
    help_cards: Mapped[list[HelpCard]] = relationship(back_populates="owner")
    help_answers: Mapped[list[HelpAnswer]] = relationship(back_populates="answer_user")
    reward_events: Mapped[list[RewardEvent]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    auth_sessions: Mapped[list[AuthSession]] = relationship(back_populates="user")
    devices: Mapped[list[UserDevice]] = relationship(back_populates="user")
    light_events: Mapped[list[LightEvent]] = relationship(back_populates="user")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped[User] = relationship(back_populates="conversations")
    turns: Mapped[list[Turn]] = relationship(back_populates="conversation")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="conversation")
    questions: Mapped[list[Question]] = relationship(back_populates="conversation")


class Turn(CreatedAtMixin, Base):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_index", name="uq_turns_conversation_id_turn_index"),
        Index("ix_turns_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="recorded", nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="turns")
    user: Mapped[User | None] = relationship(back_populates="turns")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="turn")
    questions: Mapped[list[Question]] = relationship(back_populates="turn")


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_agent_runs_run_type_status", "run_type", "status"),
        Index("ix_agent_runs_input_json", "input_json", postgresql_using="gin"),
        Index("ix_agent_runs_output_json", "output_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    run_type: Mapped[str] = mapped_column(String(100), nullable=False)
    graph_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), default="deterministic", nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), default="deterministic-v1", nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="agent_runs")
    turn: Mapped[Turn | None] = relationship(back_populates="agent_runs")
    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="agent_run")
    retrieval_runs: Mapped[list[RetrievalRun]] = relationship(back_populates="agent_run")
    recommendation_cards: Mapped[list[RecommendationCard]] = relationship(back_populates="agent_run")


class ToolCall(TimestampMixin, Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_agent_run_id_sequence_index", "agent_run_id", "sequence_index"),
        Index("ix_tool_calls_tool_name_status", "tool_name", "status"),
        Index("ix_tool_calls_arguments_json", "arguments_json", postgresql_using="gin"),
        Index("ix_tool_calls_result_json", "result_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    sequence_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent_run: Mapped[AgentRun] = relationship(back_populates="tool_calls")


class RetrievalRun(TimestampMixin, Base):
    __tablename__ = "retrieval_runs"
    __table_args__ = (
        Index("ix_retrieval_runs_agent_run_id_created_at", "agent_run_id", "created_at"),
        Index("ix_retrieval_runs_source_status", "source", "status"),
        Index("ix_retrieval_runs_filters_json", "filters_json", postgresql_using="gin"),
        Index("ix_retrieval_runs_metadata_json", "metadata_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    top_k: Mapped[int | None] = mapped_column(Integer)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent_run: Mapped[AgentRun] = relationship(back_populates="retrieval_runs")
    hits: Mapped[list[RetrievalHit]] = relationship(back_populates="retrieval_run")


class RetrievalHit(CreatedAtMixin, Base):
    __tablename__ = "retrieval_hits"
    __table_args__ = (
        UniqueConstraint(
            "retrieval_run_id",
            "rank",
            name="uq_retrieval_hits_retrieval_run_id_rank",
        ),
        Index("ix_retrieval_hits_retrieval_run_id_rank", "retrieval_run_id", "rank"),
        Index("ix_retrieval_hits_source_type_source_id", "source_type", "source_id"),
        Index("ix_retrieval_hits_payload_json", "payload_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255))
    source_uri: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    retrieval_run: Mapped[RetrievalRun] = relationship(back_populates="hits")


class Intent(TimestampMixin, Base):
    __tablename__ = "intents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    examples_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    answers: Mapped[list[IntentAnswer]] = relationship(back_populates="intent")


class ImageAsset(TimestampMixin, Base):
    __tablename__ = "image_assets"
    __table_args__ = (
        Index("ix_image_assets_verified_is_ai_generated", "verified", "is_ai_generated"),
        Index("ix_image_assets_verification_status_is_ai_generated", "verification_status", "is_ai_generated"),
        Index("ix_image_assets_displayable_verified_non_ai", "displayable", "verification_status", "is_ai_generated"),
        Index("ix_image_assets_source_domain", "source_domain"),
        Index("ix_image_assets_web_search_run_id", "web_search_run_id"),
        Index("ix_image_assets_place_key_item_key", "place_key", "item_key"),
        Index("ix_image_assets_metadata_json", "metadata_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_domain: Mapped[str | None] = mapped_column(String(255))
    credit: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    is_ai_generated: Mapped[bool] = mapped_column(default=False, nullable=False)
    ai_generated_risk: Mapped[str | None] = mapped_column(String(50))
    displayable: Mapped[bool] = mapped_column(default=False, nullable=False)
    place_key: Mapped[str | None] = mapped_column(String(255))
    item_key: Mapped[str | None] = mapped_column(String(255))
    query_text: Mapped[str | None] = mapped_column(Text)
    tavily_result_id: Mapped[str | None] = mapped_column(String(255))
    web_search_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("web_search_runs.id", ondelete="SET NULL"),
    )
    license_note: Mapped[str | None] = mapped_column(Text)
    alt_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    intent_answers: Mapped[list[IntentAnswer]] = relationship(back_populates="image_asset")
    recommendation_cards: Mapped[list[RecommendationCard]] = relationship(back_populates="image_asset")
    web_search_run: Mapped[WebSearchRun | None] = relationship(back_populates="image_assets")


class IntentAnswer(TimestampMixin, Base):
    __tablename__ = "intent_answers"
    __table_args__ = (
        Index("ix_intent_answers_intent_id_priority", "intent_id", "priority"),
        Index("ix_intent_answers_tags_json", "tags_json", postgresql_using="gin"),
        Index("ix_intent_answers_evidence_json", "evidence_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("intents.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="SET NULL"),
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent_key: Mapped[str | None] = mapped_column(String(255))
    intent_text: Mapped[str | None] = mapped_column(Text)
    answer_title: Mapped[str | None] = mapped_column(Text)
    answer_summary: Mapped[str | None] = mapped_column(Text)
    constraints_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    source_type: Mapped[str | None] = mapped_column(String(100))
    source_ref_id: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[float | None] = mapped_column(Float)
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str | None] = mapped_column(String(50))
    tags_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    intent: Mapped[Intent] = relationship(back_populates="answers")
    image_asset: Mapped[ImageAsset | None] = relationship(back_populates="intent_answers")


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index("ix_questions_user_id_created_at", "user_id", "created_at"),
        Index("ix_questions_status_created_at", "status", "created_at"),
        Index("ix_questions_context_json", "context_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_recommendation_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "recommendation_cards.id",
            name="fk_questions_current_rec_card_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )
    current_help_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "help_cards.id",
            name="fk_questions_current_help_card_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )
    context_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="questions")
    turn: Mapped[Turn | None] = relationship(back_populates="questions")
    user: Mapped[User] = relationship(back_populates="questions")
    current_recommendation_card: Mapped[RecommendationCard | None] = relationship(
        foreign_keys=[current_recommendation_card_id],
        post_update=True,
    )
    current_help_card: Mapped[HelpCard | None] = relationship(
        foreign_keys=[current_help_card_id],
        post_update=True,
    )
    recommendation_cards: Mapped[list[RecommendationCard]] = relationship(
        back_populates="question",
        foreign_keys="RecommendationCard.question_id",
    )
    help_cards: Mapped[list[HelpCard]] = relationship(
        back_populates="question",
        foreign_keys="HelpCard.question_id",
    )


class RecommendationCard(TimestampMixin, Base):
    __tablename__ = "recommendation_cards"
    __table_args__ = (
        Index("ix_recommendation_cards_question_id_created_at", "question_id", "created_at"),
        Index("ix_recommendation_cards_user_id_created_at", "user_id", "created_at"),
        Index("ix_recommendation_cards_image_asset_id", "image_asset_id"),
        Index("ix_recommendation_cards_status", "status"),
        Index("ix_recommendation_cards_payload_json", "payload_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
    )
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="SET NULL"),
    )
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="SET NULL"),
    )
    image_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    image_status: Mapped[str] = mapped_column(String(50), default="missing", nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    bullets_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    warning: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question: Mapped[Question] = relationship(
        back_populates="recommendation_cards",
        foreign_keys=[question_id],
    )
    user: Mapped[User] = relationship(back_populates="recommendation_cards")
    agent_run: Mapped[AgentRun | None] = relationship(back_populates="recommendation_cards")
    image_asset: Mapped[ImageAsset | None] = relationship(back_populates="recommendation_cards")


class WebSearchRun(CreatedAtMixin, Base):
    __tablename__ = "web_search_runs"
    __table_args__ = (
        Index("ix_web_search_runs_provider_created_at", "provider", "created_at"),
        Index("ix_web_search_runs_query_text", "query_text"),
        Index("ix_web_search_runs_response_json", "response_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_type: Mapped[str] = mapped_column(String(50), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    results: Mapped[list[WebSearchResult]] = relationship(back_populates="web_search_run")
    image_assets: Mapped[list[ImageAsset]] = relationship(back_populates="web_search_run")


class WebSearchResult(CreatedAtMixin, Base):
    __tablename__ = "web_search_results"
    __table_args__ = (
        Index("ix_web_search_results_web_search_run_id", "web_search_run_id"),
        Index("ix_web_search_results_domain", "domain"),
        Index("ix_web_search_results_raw_json", "raw_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    web_search_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("web_search_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    web_search_run: Mapped[WebSearchRun] = relationship(back_populates="results")


class AmapPoiSearchRun(CreatedAtMixin, Base):
    __tablename__ = "amap_poi_search_runs"
    __table_args__ = (
        Index("ix_amap_poi_search_runs_agent_run_id", "agent_run_id"),
        Index("ix_amap_poi_search_runs_status_created_at", "status", "created_at"),
        Index("ix_amap_poi_search_runs_request_json", "request_json", postgresql_using="gin"),
        Index("ix_amap_poi_search_runs_response_json", "response_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    city: Mapped[str | None] = mapped_column(String(100))
    keyword: Mapped[str | None] = mapped_column(String(255))
    types: Mapped[str | None] = mapped_column(String(255))
    center_lng: Mapped[float | None] = mapped_column(Float)
    center_lat: Mapped[float | None] = mapped_column(Float)
    radius_meters: Mapped[int | None] = mapped_column(Integer)
    limit: Mapped[int | None] = mapped_column(Integer)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    candidates: Mapped[list[AmapPoiCandidate]] = relationship(back_populates="search_run")


class AmapPoiCandidate(CreatedAtMixin, Base):
    __tablename__ = "amap_poi_candidates"
    __table_args__ = (
        Index("ix_amap_poi_candidates_search_run_rank", "search_run_id", "rank"),
        Index("ix_amap_poi_candidates_poi_id", "poi_id"),
        Index("ix_amap_poi_candidates_name", "name"),
        Index("ix_amap_poi_candidates_raw_json", "raw_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("amap_poi_search_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    poi_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text)
    typecode: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    lng: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    tel: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    search_run: Mapped[AmapPoiSearchRun] = relationship(back_populates="candidates")


class AmapRouteRun(CreatedAtMixin, Base):
    __tablename__ = "amap_route_runs"
    __table_args__ = (
        Index("ix_amap_route_runs_agent_run_id", "agent_run_id"),
        Index("ix_amap_route_runs_status_created_at", "status", "created_at"),
        Index("ix_amap_route_runs_request_json", "request_json", postgresql_using="gin"),
        Index("ix_amap_route_runs_response_json", "response_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    origin_lng: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lng: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lat: Mapped[float] = mapped_column(Float, nullable=False)
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    summary_text: Mapped[str | None] = mapped_column(Text)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class AgentPromptConfig(TimestampMixin, Base):
    __tablename__ = "agent_prompt_configs"
    __table_args__ = (
        UniqueConstraint("key", name="uq_agent_prompt_configs_key"),
        Index("ix_agent_prompt_configs_key_enabled", "key", "enabled"),
        Index("ix_agent_prompt_configs_prompt_type", "prompt_type"),
        Index("ix_agent_prompt_configs_config_json", "config_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class AgentPromptConfigVersion(CreatedAtMixin, Base):
    __tablename__ = "agent_prompt_config_versions"
    __table_args__ = (
        UniqueConstraint("prompt_key", "version", name="uq_agent_prompt_config_versions_key_version"),
        Index("ix_agent_prompt_config_versions_prompt_key_created_at", "prompt_key", "created_at"),
        Index("ix_agent_prompt_config_versions_config_json", "config_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_prompt_configs.id", ondelete="SET NULL"),
    )
    prompt_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)


class PromptTemplate(TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("prompt_key", name="uq_prompt_templates_prompt_key"),
        Index("ix_prompt_templates_scope", "scope"),
        Index("ix_prompt_templates_variables_schema_json", "variables_schema_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    variables_schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class PromptVersion(CreatedAtMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),
        Index("ix_prompt_versions_template_status", "template_id", "status"),
        Index("ix_prompt_versions_checksum", "checksum"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptAssignment(TimestampMixin, Base):
    __tablename__ = "prompt_assignments"
    __table_args__ = (
        UniqueConstraint("prompt_key", "environment", name="uq_prompt_assignments_key_environment"),
        Index("ix_prompt_assignments_environment", "environment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key: Mapped[str] = mapped_column(String(255), nullable=False)
    active_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    environment: Mapped[str] = mapped_column(String(50), default="staging", nullable=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class PromptPublishEvent(CreatedAtMixin, Base):
    __tablename__ = "prompt_publish_events"
    __table_args__ = (
        Index("ix_prompt_publish_events_prompt_key_published_at", "prompt_key", "published_at"),
        Index("ix_prompt_publish_events_dry_run_result_json", "dry_run_result_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key: Mapped[str] = mapped_column(String(255), nullable=False)
    from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
    )
    to_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dry_run_result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    published_by: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PromptAuditLog(CreatedAtMixin, Base):
    __tablename__ = "prompt_audit_logs"
    __table_args__ = (
        Index("ix_prompt_audit_logs_prompt_key_created_at", "prompt_key", "created_at"),
        Index("ix_prompt_audit_logs_action", "action"),
        Index("ix_prompt_audit_logs_before_json", "before_json", postgresql_using="gin"),
        Index("ix_prompt_audit_logs_after_json", "after_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)


class PromptReplayRun(CreatedAtMixin, Base):
    __tablename__ = "prompt_replay_runs"
    __table_args__ = (
        Index("ix_prompt_replay_runs_prompt_key_created_at", "prompt_key", "created_at"),
        Index("ix_prompt_replay_runs_status_created_at", "status", "created_at"),
        Index("ix_prompt_replay_runs_input_json", "input_json", postgresql_using="gin"),
        Index("ix_prompt_replay_runs_output_json", "output_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    candidate_version: Mapped[int | None] = mapped_column(Integer)
    admin_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)


class AgentAbilityConfig(TimestampMixin, Base):
    __tablename__ = "agent_ability_configs"
    __table_args__ = (
        UniqueConstraint("key", name="uq_agent_ability_configs_key"),
        Index("ix_agent_ability_configs_key_enabled", "key", "enabled"),
        Index("ix_agent_ability_configs_tool_name", "tool_name"),
        Index("ix_agent_ability_configs_ability_type", "ability_type"),
        Index("ix_agent_ability_configs_trigger_intents_json", "trigger_intents_json", postgresql_using="gin"),
        Index("ix_agent_ability_configs_config_json", "config_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ability_type: Mapped[str] = mapped_column(String(100), default="builtin_tool", nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    runtime_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger_intents_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_contract_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    guardrails_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    prompt_keys_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class OpsMetricSnapshot(CreatedAtMixin, Base):
    __tablename__ = "ops_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "bucket",
            "bucket_start",
            "metric_key",
            "dimension_key",
            name="uq_ops_metric_snapshots_bucket_metric",
        ),
        Index("ix_ops_metric_snapshots_bucket_start", "bucket", "bucket_start"),
        Index("ix_ops_metric_snapshots_metric_key", "metric_key"),
        Index("ix_ops_metric_snapshots_dimensions_json", "dimensions_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bucket: Mapped[str] = mapped_column(String(50), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(255), default="global", nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(100), default="admin_runtime", nullable=False)


class ContentReviewTask(TimestampMixin, Base):
    __tablename__ = "content_review_tasks"
    __table_args__ = (
        Index("ix_content_review_tasks_status_priority", "status", "priority"),
        Index("ix_content_review_tasks_task_type_created_at", "task_type", "created_at"),
        Index("ix_content_review_tasks_target", "target_table", "target_record_id"),
        Index("ix_content_review_tasks_payload_json", "payload_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    target_table: Mapped[str] = mapped_column(String(255), nullable=False)
    target_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(255))


class HelpCard(TimestampMixin, Base):
    __tablename__ = "help_cards"
    __table_args__ = (
        Index("ix_help_cards_question_id", "question_id"),
        Index("ix_help_cards_owner_user_id_status", "owner_user_id", "status"),
        Index("ix_help_cards_status_answer_count", "status", "answer_count"),
        Index("ix_help_cards_payload_json", "payload_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    answer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_answers_required: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    final_recommendation_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "recommendation_cards.id",
            name="fk_help_cards_final_rec_card_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question: Mapped[Question] = relationship(
        back_populates="help_cards",
        foreign_keys=[question_id],
    )
    owner: Mapped[User] = relationship(back_populates="help_cards")
    final_recommendation_card: Mapped[RecommendationCard | None] = relationship(
        foreign_keys=[final_recommendation_card_id],
        post_update=True,
    )
    answers: Mapped[list[HelpAnswer]] = relationship(back_populates="help_card")


class HelpAnswer(CreatedAtMixin, Base):
    __tablename__ = "help_answers"
    __table_args__ = (
        Index("ix_help_answers_help_card_id_created_at", "help_card_id", "created_at"),
        Index("ix_help_answers_answer_user_id", "answer_user_id"),
        Index("ix_help_answers_evidence_json", "evidence_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    help_card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("help_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reward_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    help_card: Mapped[HelpCard] = relationship(back_populates="answers")
    answer_user: Mapped[User | None] = relationship(back_populates="help_answers")
    reward_events: Mapped[list[RewardEvent]] = relationship(back_populates="help_answer")


class RewardEvent(CreatedAtMixin, Base):
    __tablename__ = "reward_events"
    __table_args__ = (
        Index("ix_reward_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_reward_events_help_card_id", "help_card_id"),
        Index("ix_reward_events_help_answer_id", "help_answer_id"),
        Index("ix_reward_events_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    help_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("help_cards.id", ondelete="SET NULL"))
    help_answer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("help_answers.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped[User] = relationship(back_populates="reward_events")
    help_answer: Mapped[HelpAnswer | None] = relationship(back_populates="reward_events")


class EmailLoginCode(TimestampMixin, Base):
    __tablename__ = "email_login_codes"
    __table_args__ = (
        Index("ix_email_login_codes_email_status_expires_at", "email", "status", "expires_at"),
        Index("ix_email_login_codes_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), default="login", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(Text)
    device_uid: Mapped[str | None] = mapped_column(String(255))


class AuthSession(CreatedAtMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_id_status", "user_id", "status"),
        Index("ix_auth_sessions_refresh_token_hash", "refresh_token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_uid: Mapped[str | None] = mapped_column(String(255))
    refresh_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="auth_sessions")


class AuthAuditLog(CreatedAtMixin, Base):
    __tablename__ = "auth_audit_logs"
    __table_args__ = (
        Index("ix_auth_audit_logs_email_created_at", "email", "created_at"),
        Index("ix_auth_audit_logs_action_created_at", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    email: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class UserDevice(TimestampMixin, Base):
    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_uid", name="uq_user_devices_user_id_device_uid"),
        Index("ix_user_devices_device_uid", "device_uid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(50))
    app_version: Mapped[str | None] = mapped_column(String(50))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="devices")


class LightEvent(CreatedAtMixin, Base):
    __tablename__ = "light_events"
    __table_args__ = (
        Index("ix_light_events_user_id_lit_at", "user_id", "lit_at"),
        Index("ix_light_events_type", "type"),
        Index("ix_light_events_payload_json", "payload_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    help_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("help_cards.id", ondelete="SET NULL"))
    recommendation_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendation_cards.id", ondelete="SET NULL"),
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    lit_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="light_events")


class AdminAuditLog(CreatedAtMixin, Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_admin_audit_logs_created_at", "created_at"),
        Index("ix_admin_audit_logs_table_action", "target_table", "action"),
        Index("ix_admin_audit_logs_target_record", "target_table", "target_record_id"),
        Index("ix_admin_audit_logs_request_json", "request_json", postgresql_using="gin"),
        Index("ix_admin_audit_logs_before_json", "before_json", postgresql_using="gin"),
        Index("ix_admin_audit_logs_after_json", "after_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_table: Mapped[str] = mapped_column(String(255), nullable=False)
    target_record_id: Mapped[str | None] = mapped_column(String(255))
    request_path: Mapped[str | None] = mapped_column(Text)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(255))
    user_agent: Mapped[str | None] = mapped_column(Text)
