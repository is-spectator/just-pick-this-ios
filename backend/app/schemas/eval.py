"""Eval-only API schemas for pipi-eval-lab."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvalResetRequest(ApiModel):
    eval_run_id: str


class EvalResetResponse(ApiModel):
    ok: bool = True
    reset_at: datetime


class EvalSeedFoodRequest(ApiModel):
    mode: str = "minimal"
    with_approved_answers: bool = True


class EvalSeedFoodResponse(ApiModel):
    ok: bool = True
    pack_id: str
    seeded: dict[str, int]


class EvalSeedNegativeResponse(ApiModel):
    ok: bool = True


class EvalSeedStatusResponse(ApiModel):
    pack_id: str
    area_anchor_count: int
    venue_count: int
    area_intent_answer_count: int
    ordering_bundle_answer_count: int
    last_seeded_at: datetime | None = None


class EvalTraceConversationResponse(ApiModel):
    conversation_id: str
    turns: list[dict[str, Any]] = Field(default_factory=list)
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_runs: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_hits: list[dict[str, Any]] = Field(default_factory=list)


class EvalTraceTurnResponse(ApiModel):
    turn_id: str
    agent_run: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_run: dict[str, Any] | None = None
    retrieval_hits: list[dict[str, Any]] = Field(default_factory=list)
