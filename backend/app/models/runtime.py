from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
