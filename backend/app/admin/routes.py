from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, cast, exists, func, inspect, or_, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db_session
from app.debug.routes import (
    _extract_intent,
    _serialize_agent_run,
    _serialize_conversation_summary,
    _serialize_turn,
    _shadow_decision_diffs,
    _shadow_reasoner_events,
    _shadow_summary,
)
from app.models import (
    AdminAuditLog,
    AgentAbilityConfig,
    AgentRun,
    AgentPromptConfig,
    AgentPromptConfigVersion,
    Conversation,
    ContentReviewTask,
    HelpAnswer,
    HelpCard,
    ImageAsset,
    Intent,
    IntentAnswer,
    LightEvent,
    OpsMetricSnapshot,
    PromptReplayRun,
    Question,
    RecommendationCard,
    RetrievalHit,
    RetrievalRun,
    ToolCall,
    Turn,
    User,
    UserBehaviorEvent,
    WebSearchResult,
    WebSearchRun,
)
from app.services.ability_config import list_ability_configs, serialize_ability_config, upsert_ability_config
from app.services.eval_review_service import (
    case_detail as eval_case_detail,
    list_eval_runs as list_eval_report_runs,
    low_quality_cases as eval_low_quality_cases,
    resolve_reports_root,
    review_payload as build_eval_review_payload,
)
from app.services.intent_answer_import import (
    import_intent_answer_drafts,
    serialize_imported_intent_answer,
)
from app.services.runtime_latency import runtime_latency_summary
from app.services.prompt_config import (
    list_prompt_configs,
    list_prompt_versions,
    rollback_prompt_config,
    run_prompt_replay,
    serialize_prompt_replay,
    upsert_prompt_config,
)
from app.services.seed_patch_workflow import (
    create_seed_intent_answer_draft,
    latest_accepted_seed_patch,
    serialize_seed_intent_answer_draft,
)


def _settings(request: Request) -> Any:
    settings = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def _require_admin(request: Request) -> str:
    configured = _settings(request).admin_token
    if configured is None:
        raise HTTPException(status_code=401, detail="admin token required")

    expected = configured.get_secret_value()
    authorization = request.headers.get("authorization") or ""
    bearer = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not bearer or not compare_digest(bearer, expected):
        raise HTTPException(status_code=401, detail="admin token required")

    actor = request.headers.get("x-admin-actor") or "admin-token"
    role = request.headers.get("x-admin-role") or "admin"
    request.state.admin_actor = actor
    request.state.admin_role = role
    return actor


def _admin_actor(request: Request) -> str:
    actor = getattr(request.state, "admin_actor", None)
    if isinstance(actor, str) and actor:
        return actor
    return _require_admin(request)


def _admin_role(request: Request) -> str:
    role = getattr(request.state, "admin_role", None)
    if isinstance(role, str) and role:
        return role
    _require_admin(request)
    return str(getattr(request.state, "admin_role", "admin"))


def _require_admin_role(request: Request, allowed: set[str]) -> None:
    role = _admin_role(request)
    if role not in allowed:
        raise HTTPException(status_code=403, detail="admin role is not allowed for this action")


def _optional_mapping(value: Any, *, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=422, detail=f"{field_name} must be an object")
    return dict(value)


def _optional_mapping_or_text(value: Any, *, field_name: str) -> dict[str, Any] | str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return dict(value)
    raise HTTPException(status_code=422, detail=f"{field_name} must be an object or string")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(_require_admin)])

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_ADMIN_HTML = _STATIC_DIR / "admin.html"


@dataclass(frozen=True)
class TableConfig:
    model: type[Any]
    read_only: bool = False


TABLES: dict[str, TableConfig] = {
    "users": TableConfig(User),
    "conversations": TableConfig(Conversation),
    "turns": TableConfig(Turn),
    "agent_runs": TableConfig(AgentRun),
    "agent_ability_configs": TableConfig(AgentAbilityConfig),
    "agent_prompt_configs": TableConfig(AgentPromptConfig),
    "agent_prompt_config_versions": TableConfig(AgentPromptConfigVersion, read_only=True),
    "prompt_replay_runs": TableConfig(PromptReplayRun, read_only=True),
    "ops_metric_snapshots": TableConfig(OpsMetricSnapshot, read_only=True),
    "content_review_tasks": TableConfig(ContentReviewTask),
    "tool_calls": TableConfig(ToolCall),
    "retrieval_runs": TableConfig(RetrievalRun),
    "retrieval_hits": TableConfig(RetrievalHit),
    "intents": TableConfig(Intent),
    "intent_answers": TableConfig(IntentAnswer),
    "image_assets": TableConfig(ImageAsset),
    "questions": TableConfig(Question),
    "recommendation_cards": TableConfig(RecommendationCard),
    "help_cards": TableConfig(HelpCard),
    "help_answers": TableConfig(HelpAnswer),
    "user_behavior_events": TableConfig(UserBehaviorEvent, read_only=True),
    "light_events": TableConfig(LightEvent),
    "web_search_runs": TableConfig(WebSearchRun),
    "web_search_results": TableConfig(WebSearchResult),
    "admin_audit_logs": TableConfig(AdminAuditLog, read_only=True),
}

RUNTIME_TABLES = {
    "agent_runs",
    "tool_calls",
    "turns",
    "retrieval_runs",
    "retrieval_hits",
}
CORE_DELETE_DENYLIST = {
    "users",
    "conversations",
    "turns",
    "agent_runs",
    "tool_calls",
    "retrieval_runs",
    "retrieval_hits",
    "admin_audit_logs",
}


@router.get("", include_in_schema=False)
def admin_root() -> RedirectResponse:
    return RedirectResponse(url="/admin/sessions")


@router.get("/sessions", response_class=HTMLResponse, include_in_schema=False)
def admin_page(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    actor = _admin_actor(request)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="view_page",
        table_name="admin_console",
        target_record_id=None,
        request_json=_request_json(request),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return HTMLResponse(_ADMIN_HTML.read_text(encoding="utf-8"))


@router.get("/api/sessions")
def list_admin_sessions(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    query = select(Conversation).join(User, Conversation.user_id == User.id)
    conditions: list[Any] = []
    if status:
        conditions.append(Conversation.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                cast(Conversation.id, String).ilike(pattern),
                Conversation.title.ilike(pattern),
                User.device_uid.ilike(pattern),
                User.display_name.ilike(pattern),
                exists(
                    select(Turn.id).where(
                        Turn.conversation_id == Conversation.id,
                        Turn.content.ilike(pattern),
                    )
                ),
            )
        )
    if intent:
        conditions.append(
            exists(
                select(AgentRun.id).where(
                    AgentRun.conversation_id == Conversation.id,
                    AgentRun.output_json["intent"].as_string() == intent,
                )
            )
        )
    if conditions:
        query = query.where(*conditions)

    total = _query_count(session, query)
    conversations = session.scalars(
        query.order_by(Conversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="sessions",
        target_record_id=None,
        request_json=_request_json(request, {"page": page, "page_size": page_size, "total": total}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {
        "items": [_serialize_conversation_summary(session, item) for item in conversations],
        "pagination": _pagination(page=page, page_size=page_size, total=total),
    }


@router.get("/api/runtime-latency")
def admin_runtime_latency(
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    summary = runtime_latency_summary(session, hours=hours, limit=limit)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="view_runtime_latency",
        table_name="runtime_latency",
        target_record_id=None,
        request_json=_request_json(request, {"hours": hours, "limit": limit}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return summary


@router.get("/api/eval-runs")
def list_eval_runs(request: Request) -> dict[str, Any]:
    reports_root = resolve_reports_root(getattr(request.app.state, "eval_reports_root", None))
    return {"items": list_eval_report_runs(reports_root), "reports_root": str(reports_root)}


@router.get("/api/eval-runs/{run_id}/low-quality-cases")
def list_eval_low_quality_cases(
    request: Request,
    run_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    primary_cause: str | None = Query(default=None),
) -> dict[str, Any]:
    reports_root = resolve_reports_root(getattr(request.app.state, "eval_reports_root", None))
    return {
        "run_id": run_id,
        "items": eval_low_quality_cases(
            reports_root,
            run_id,
            limit=limit,
            primary_cause=primary_cause,
        ),
    }


@router.get("/api/eval-runs/{run_id}/cases/{case_id}")
def get_eval_case_detail(request: Request, run_id: str, case_id: str) -> dict[str, Any]:
    reports_root = resolve_reports_root(getattr(request.app.state, "eval_reports_root", None))
    try:
        return eval_case_detail(reports_root, run_id, case_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="eval case not found") from exc


@router.post("/api/eval-runs/{run_id}/cases/{case_id}/review")
def review_eval_case(
    request: Request,
    run_id: str,
    case_id: str,
    payload: dict[str, Any],
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    action = str(payload.get("action") or "").strip()
    if action not in {"accept_seed_gap", "mark_agent_bug", "mark_not_issue", "needs_more_data"}:
        raise HTTPException(status_code=422, detail="invalid review action")
    labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
    suggested_fix = _optional_mapping_or_text(payload.get("suggested_fix"), field_name="suggested_fix")
    seed_patch = _optional_mapping(payload.get("seed_patch"), field_name="seed_patch")
    review = build_eval_review_payload(
        run_id=run_id,
        case_id=case_id,
        action=action,
        reviewer=actor,
        notes=str(payload.get("notes") or ""),
        labels=[str(label) for label in labels],
        suggested_fix=suggested_fix,
        seed_patch=seed_patch,
    )
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="review_eval_case",
        table_name="eval_run_cases",
        target_record_id=f"{run_id}:{case_id}",
        request_json=_request_json(request, extra={"review": review}),
        before_json=None,
        after_json=review,
    )
    session.commit()
    return {"ok": True, "review": review}


@router.post("/api/eval-runs/{run_id}/cases/{case_id}/seed-intent-answer-draft")
def create_eval_seed_intent_answer_draft(
    request: Request,
    run_id: str,
    case_id: str,
    payload: dict[str, Any] | None = None,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    body = payload or {}
    seed_patch = _optional_mapping(body.get("seed_patch"), field_name="seed_patch")
    if seed_patch is None:
        seed_patch = latest_accepted_seed_patch(session, run_id=run_id, case_id=case_id)
    if seed_patch is None:
        raise HTTPException(status_code=404, detail="accepted seed_patch not found")

    try:
        answer = create_seed_intent_answer_draft(
            session,
            run_id=run_id,
            case_id=case_id,
            seed_patch=seed_patch,
            reviewer=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    draft = serialize_seed_intent_answer_draft(answer)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="create_seed_intent_answer_draft",
        table_name="intent_answers",
        target_record_id=str(answer.id),
        request_json=_request_json(
            request,
            extra={"run_id": run_id, "case_id": case_id, "seed_patch": seed_patch},
        ),
        before_json=None,
        after_json=draft,
    )
    session.commit()
    return {"ok": True, "intent_answer": draft}


@router.post("/api/intent-answers/import-drafts")
def import_admin_intent_answer_drafts(
    request: Request,
    payload: dict[str, Any],
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "content_ops"})
    actor = _admin_actor(request)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=422, detail="items must be a non-empty list")
    for index, item in enumerate(raw_items):
        if not isinstance(item, Mapping):
            raise HTTPException(status_code=422, detail=f"items[{index}] must be an object")
    activate = bool(payload.get("activate", False))
    try:
        answers = import_intent_answer_drafts(
            session,
            items=raw_items,
            reviewer=actor,
            activate=activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    imported = [serialize_imported_intent_answer(answer) for answer in answers]
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="import_intent_answer_drafts",
        table_name="intent_answers",
        target_record_id=None,
        request_json=_request_json(request, extra={"item_count": len(raw_items), "activate": activate}),
        before_json=None,
        after_json={"items": imported},
    )
    session.commit()
    return {"ok": True, "count": len(imported), "items": imported}


@router.get("/api/sessions/{conversation_id}")
def get_admin_session(
    conversation_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    conversation = _get_uuid_row(session, Conversation, conversation_id, "session not found")
    turns = session.scalars(
        select(Turn)
        .where(Turn.conversation_id == conversation.id)
        .order_by(Turn.turn_index.asc(), Turn.created_at.asc())
    ).all()
    traces = session.scalars(
        select(AgentRun)
        .where(AgentRun.conversation_id == conversation.id)
        .order_by(AgentRun.started_at.asc(), AgentRun.created_at.asc())
    ).all()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="sessions",
        target_record_id=conversation_id,
        request_json=_request_json(request),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {
        "session": _serialize_conversation_summary(session, conversation),
        "turns": [_serialize_turn(item) for item in turns],
        "traces": [_serialize_agent_run(session, item) for item in traces],
    }


@router.get("/api/traces")
def list_admin_traces(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    conversation_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    graph_name: str | None = Query(default=None),
    q: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    query = select(AgentRun)
    conditions: list[Any] = []
    if conversation_id:
        conditions.append(AgentRun.conversation_id == _parse_uuid(conversation_id, "conversation_id"))
    if status:
        conditions.append(AgentRun.status == status)
    if graph_name:
        conditions.append(AgentRun.graph_name == graph_name)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                cast(AgentRun.id, String).ilike(pattern),
                cast(AgentRun.conversation_id, String).ilike(pattern),
                AgentRun.run_type.ilike(pattern),
                AgentRun.graph_name.ilike(pattern),
                AgentRun.model_provider.ilike(pattern),
                AgentRun.model_name.ilike(pattern),
                AgentRun.error_message.ilike(pattern),
                cast(AgentRun.input_json, String).ilike(pattern),
                cast(AgentRun.output_json, String).ilike(pattern),
            )
        )
    if conditions:
        query = query.where(*conditions)

    total = _query_count(session, query)
    runs = session.scalars(
        query.order_by(AgentRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="agent_runs",
        target_record_id=None,
        request_json=_request_json(request, {"page": page, "page_size": page_size, "total": total}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {
        "items": [_serialize_trace_summary(item) for item in runs],
        "pagination": _pagination(page=page, page_size=page_size, total=total),
    }


@router.get("/api/traces/{trace_id}")
def get_admin_trace(
    trace_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    run = _get_uuid_row(session, AgentRun, trace_id, "trace not found")
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="agent_runs",
        target_record_id=trace_id,
        request_json=_request_json(request),
        before_json=None,
        after_json=None,
    )
    session.commit()
    serialized = _serialize_agent_run(session, run)
    shadow_summary = serialized.get("shadow_summary")
    shadow_diffs = _admin_shadow_decision_diffs(serialized.get("shadow_decision_diffs"))
    return {
        "trace": serialized,
        "shadow_summary": shadow_summary,
        "shadow_decision_diffs": shadow_diffs,
    }


@router.get("/api/metrics/overview")
def get_admin_metrics_overview(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    scope: str = Query(default="product", pattern="^(product|all)$"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    window = _window(days)
    overview = {
        "generated_at": _utcnow().isoformat(),
        "data_source": {
            "kind": "postgresql",
            "scope": "live_database",
            "metric_scope": scope,
            "synthetic": False,
            "note": _metric_scope_note(scope),
        },
        "window": _window_payload(window),
        "users": {
            "total": _count_users(session, scope=scope),
            "new": _count_users(session, scope=scope, date_column=User.created_at, start=window["start"]),
            "active": _count_users(session, scope=scope, date_column=User.last_seen_at, start=window["start"]),
            "dau": _count_users(session, scope=scope, date_column=User.last_seen_at, start=window["today_start"]),
            "turn_active": _count_turn_users_since(session, window["start"], scope=scope),
        },
        "runtime": {
            "conversations": _count_since(session, Conversation, Conversation.created_at, window["start"], scope=scope),
            "turns": _count_since(session, Turn, Turn.created_at, window["start"], scope=scope),
            "agent_runs": _count_since(session, AgentRun, AgentRun.created_at, window["start"], scope=scope),
            "tool_calls": _count_since(session, ToolCall, ToolCall.created_at, window["start"], scope=scope),
            "retrieval_runs": _count_since(session, RetrievalRun, RetrievalRun.created_at, window["start"], scope=scope),
        },
        "outcomes": _outcome_counts(session, window["start"], scope=scope),
        "quality": _failure_counts(session, window["start"], scope=scope),
    }
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_metrics_overview",
        target_record_id=None,
        request_json=_request_json(request, {"days": days, "scope": scope}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return overview


@router.get("/api/metrics/activity")
def get_admin_metrics_activity(
    request: Request,
    days: int = Query(default=14, ge=1, le=90),
    scope: str = Query(default="product", pattern="^(product|all)$"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    window = _window(days)
    buckets = _daily_buckets(window["start"], window["end"])
    for user in _scoped_rows(session, User, User.created_at, window["start"], scope=scope):
        _bucket_inc(buckets, user.created_at, "new_users")
    for user in _scoped_rows(session, User, User.last_seen_at, window["start"], scope=scope):
        _bucket_set_add(buckets, user.last_seen_at, "active_user_ids", str(user.id))
    for turn in _scoped_rows(session, Turn, Turn.created_at, window["start"], scope=scope):
        _bucket_inc(buckets, turn.created_at, "turns")
        if turn.user_id:
            _bucket_set_add(buckets, turn.created_at, "turn_user_ids", str(turn.user_id))
    for run in _scoped_rows(session, AgentRun, AgentRun.created_at, window["start"], scope=scope):
        _bucket_inc(buckets, run.created_at, "agent_runs")
    for card in _scoped_rows(session, RecommendationCard, RecommendationCard.created_at, window["start"], scope=scope):
        _bucket_inc(buckets, card.created_at, "recommendation_cards")
        if card.accepted_at:
            _bucket_inc(buckets, card.accepted_at, "accepted_cards")
    for card in _scoped_rows(session, HelpCard, HelpCard.created_at, window["start"], scope=scope):
        _bucket_inc(buckets, card.created_at, "help_cards")
    for event in _scoped_rows(session, LightEvent, LightEvent.created_at, window["start"], scope=scope):
        _bucket_inc(buckets, event.created_at, "light_events")
        if event.seen_at:
            _bucket_inc(buckets, event.seen_at, "seen_light_events")

    items = []
    for bucket in buckets.values():
        active_user_ids = bucket.pop("active_user_ids", set())
        turn_user_ids = bucket.pop("turn_user_ids", set())
        bucket["active_users"] = len(active_user_ids)
        bucket["turn_users"] = len(turn_user_ids)
        items.append(bucket)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_metrics_activity",
        target_record_id=None,
        request_json=_request_json(request, {"days": days, "scope": scope}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"window": _window_payload(window), "items": items}


@router.get("/api/metrics/funnel")
def get_admin_metrics_funnel(
    request: Request,
    days: int = Query(default=30, ge=1, le=180),
    scope: str = Query(default="product", pattern="^(product|all)$"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    window = _window(days)
    counts = {
        "user_turns": _count_since(session, Turn, Turn.created_at, window["start"], Turn.role == "user", scope=scope),
        "questions": _count_since(session, Question, Question.created_at, window["start"], scope=scope),
        "agent_runs": _count_since(session, AgentRun, AgentRun.created_at, window["start"], scope=scope),
        "retrieval_runs": _count_since(session, RetrievalRun, RetrievalRun.created_at, window["start"], scope=scope),
        "tool_calls": _count_since(session, ToolCall, ToolCall.created_at, window["start"], scope=scope),
        "recommendation_cards": _count_since(
            session,
            RecommendationCard,
            RecommendationCard.created_at,
            window["start"],
            scope=scope,
        ),
        "help_cards": _count_since(session, HelpCard, HelpCard.created_at, window["start"], scope=scope),
        "help_answers": _count_since(session, HelpAnswer, HelpAnswer.created_at, window["start"], scope=scope),
        "final_cards": _count_since(
            session,
            HelpCard,
            HelpCard.created_at,
            window["start"],
            HelpCard.final_recommendation_card_id.is_not(None),
            scope=scope,
        ),
        "accepted_cards": _count_since(
            session,
            RecommendationCard,
            RecommendationCard.created_at,
            window["start"],
            RecommendationCard.accepted_at.is_not(None),
            scope=scope,
        ),
        "light_events": _count_since(session, LightEvent, LightEvent.created_at, window["start"], scope=scope),
    }
    rates = {
        "recommendation_per_question": _rate(counts["recommendation_cards"], counts["questions"]),
        "help_per_question": _rate(counts["help_cards"], counts["questions"]),
        "final_per_help_card": _rate(counts["final_cards"], counts["help_cards"]),
        "accept_per_recommendation": _rate(counts["accepted_cards"], counts["recommendation_cards"]),
    }
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_metrics_funnel",
        target_record_id=None,
        request_json=_request_json(request, {"days": days, "scope": scope}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"window": _window_payload(window), "counts": counts, "rates": rates}


@router.get("/api/metrics/failures")
def get_admin_metrics_failures(
    request: Request,
    days: int = Query(default=30, ge=1, le=180),
    scope: str = Query(default="product", pattern="^(product|all)$"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    window = _window(days)
    failures = _failure_counts(session, window["start"], scope=scope)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_metrics_failures",
        target_record_id=None,
        request_json=_request_json(request, {"days": days, "scope": scope}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"window": _window_payload(window), "items": failures}


@router.get("/api/content/tasks")
def list_content_review_tasks(
    request: Request,
    status: str | None = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    persisted_query = select(ContentReviewTask)
    if status:
        persisted_query = persisted_query.where(ContentReviewTask.status == status)
    persisted = session.scalars(
        persisted_query.order_by(ContentReviewTask.priority.asc(), ContentReviewTask.created_at.desc()).limit(limit)
    ).all()
    generated = _generated_content_tasks(session, limit=limit)
    items = [_serialize_content_task(item, source="db") for item in persisted]
    seen = {(item["target_table"], item["target_record_id"], item["task_type"]) for item in items}
    for item in generated:
        key = (item["target_table"], item["target_record_id"], item["task_type"])
        if key not in seen:
            items.append(item)
            seen.add(key)
        if len(items) >= limit:
            break
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="content_review_tasks",
        target_record_id=None,
        request_json=_request_json(request, {"status": status, "limit": limit, "total": len(items)}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": items, "generated_count": sum(1 for item in items if item.get("source") == "generated")}


@router.get("/api/prompts")
def list_admin_prompts(
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    items = list_prompt_configs(session)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="agent_prompt_configs",
        target_record_id=None,
        request_json=_request_json(request, {"total": len(items)}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": items}


@router.get("/api/abilities")
def list_admin_abilities(
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    items = list_ability_configs(session)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="agent_ability_configs",
        target_record_id=None,
        request_json=_request_json(request, {"total": len(items)}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": items}


@router.put("/api/abilities/{ability_key}")
def update_admin_ability(
    ability_key: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "prompt_editor"})
    actor = _admin_actor(request)
    before = session.scalar(select(AgentAbilityConfig).where(AgentAbilityConfig.key == ability_key))
    before_json = serialize_ability_config(before, source="db") if before is not None else None
    row = upsert_ability_config(session, ability_key, payload, actor=actor)
    after_json = serialize_ability_config(row, source="db")
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="update",
        table_name="agent_ability_configs",
        target_record_id=str(row.id),
        request_json=payload,
        before_json=before_json,
        after_json=after_json,
    )
    session.commit()
    return {"item": after_json, "hot_reload": "next_chat_turn"}


@router.put("/api/prompts/{prompt_key}")
def update_admin_prompt(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "prompt_editor"})
    actor = _admin_actor(request)
    before = session.scalar(select(AgentPromptConfig).where(AgentPromptConfig.key == prompt_key))
    before_json = _row_dict(before) if before is not None else None
    row = upsert_prompt_config(session, prompt_key, payload, actor=actor)
    after_json = _row_dict(row)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="update",
        table_name="agent_prompt_configs",
        target_record_id=str(row.id),
        request_json=payload,
        before_json=before_json,
        after_json=after_json,
    )
    session.commit()
    return {"item": after_json, "hot_reload": "next_chat_turn"}


@router.get("/api/prompts/{prompt_key}/versions")
def list_admin_prompt_versions(
    prompt_key: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    items = list_prompt_versions(session, prompt_key)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="agent_prompt_config_versions",
        target_record_id=prompt_key,
        request_json=_request_json(request, {"total": len(items)}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": items}


@router.post("/api/prompts/{prompt_key}/replay")
def replay_admin_prompt(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "prompt_editor"})
    actor = _admin_actor(request)
    run = run_prompt_replay(session, prompt_key, payload, actor=actor)
    item = serialize_prompt_replay(run)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="replay",
        table_name="prompt_replay_runs",
        target_record_id=str(run.id),
        request_json=payload,
        before_json=None,
        after_json=item,
    )
    session.commit()
    return {"item": item}


@router.post("/api/prompts/{prompt_key}/rollback")
def rollback_admin_prompt(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "prompt_editor"})
    actor = _admin_actor(request)
    before = session.scalar(select(AgentPromptConfig).where(AgentPromptConfig.key == prompt_key))
    before_json = _row_dict(before) if before is not None else None
    try:
        version = int(payload.get("version"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="version is required") from exc
    try:
        row = rollback_prompt_config(
            session,
            prompt_key,
            version=version,
            actor=actor,
            notes=payload.get("notes"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    after_json = _row_dict(row)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="rollback",
        table_name="agent_prompt_configs",
        target_record_id=str(row.id),
        request_json=payload,
        before_json=before_json,
        after_json=after_json,
    )
    session.commit()
    return {"item": after_json, "rolled_back_to_version": version, "hot_reload": "next_chat_turn"}


@router.get("/api/tables")
def list_admin_tables(
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    items = []
    for name, config in TABLES.items():
        model = config.model
        items.append(
            {
                "name": name,
                "read_only": _is_table_read_only(name, config, request),
                "primary_key": _pk_column(model).key,
                "row_count": _table_count(session, model),
                "columns": [_column_metadata(column) for column in inspect(model).columns],
            }
        )
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="admin_tables",
        target_record_id=None,
        request_json=_request_json(request, {"total": len(items)}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": items}


@router.get("/api/tables/{table_name}/rows")
def list_table_rows(
    table_name: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _admin_actor(request)
    config = _table_config(table_name)
    model = config.model
    query = select(model)
    if q:
        query = query.where(_search_condition(model, q))

    sort_column = _column_by_name(model, sort) if sort else _default_sort_column(model)
    ordered = sort_column.asc() if order == "asc" else sort_column.desc()
    total = _query_count(session, query)
    rows = session.scalars(query.order_by(ordered).offset((page - 1) * page_size).limit(page_size)).all()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name=table_name,
        target_record_id=None,
        request_json=_request_json(request, {"page": page, "page_size": page_size, "total": total}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {
        "table": _table_metadata(table_name, config, session, request),
        "items": [_row_dict(item) for item in rows],
        "pagination": _pagination(page=page, page_size=page_size, total=total),
    }


@router.post("/api/tables/{table_name}/rows")
def insert_table_row(
    table_name: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "content_ops"})
    actor = _admin_actor(request)
    config = _writable_table_config(table_name, request)
    model = config.model
    values = _coerce_payload(model, payload, for_insert=True)
    _validate_table_values(table_name, values)
    row = model(**values)
    session.add(row)
    session.flush()
    after = _row_dict(row)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="insert",
        table_name=table_name,
        target_record_id=_row_id(row),
        request_json=payload,
        before_json=None,
        after_json=after,
    )
    session.commit()
    return {"item": after}


@router.patch("/api/tables/{table_name}/rows/{row_id}")
def update_table_row(
    table_name: str,
    row_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin", "content_ops"})
    actor = _admin_actor(request)
    config = _writable_table_config(table_name, request)
    model = config.model
    row = _get_row(session, model, row_id)
    before = _row_dict(row)
    values = _coerce_payload(model, payload, for_insert=False)
    _validate_table_values(table_name, values)
    pk_name = _pk_column(model).key
    for key, value in values.items():
        if key != pk_name:
            setattr(row, key, value)
    session.flush()
    after = _row_dict(row)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="update",
        table_name=table_name,
        target_record_id=_row_id(row),
        request_json=payload,
        before_json=before,
        after_json=after,
    )
    session.commit()
    return {"item": after}


@router.delete("/api/tables/{table_name}/rows/{row_id}")
def delete_table_row(
    table_name: str,
    row_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_admin_role(request, {"admin"})
    actor = _admin_actor(request)
    if table_name in CORE_DELETE_DENYLIST:
        raise HTTPException(status_code=403, detail="deleting core runtime data is disabled")
    config = _writable_table_config(table_name, request)
    model = config.model
    row = _get_row(session, model, row_id)
    before = _row_dict(row)
    session.delete(row)
    session.flush()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="delete",
        table_name=table_name,
        target_record_id=row_id,
        request_json={},
        before_json=before,
        after_json=None,
    )
    session.commit()
    return {"deleted": True, "id": row_id}

def _table_config(table_name: str) -> TableConfig:
    config = TABLES.get(table_name)
    if config is None:
        raise HTTPException(status_code=404, detail="admin table not found")
    return config


def _writable_table_config(table_name: str, request: Request) -> TableConfig:
    config = _table_config(table_name)
    if _is_table_read_only(table_name, config, request):
        raise HTTPException(status_code=403, detail="admin table is read-only")
    return config


def _serialize_trace_summary(run: AgentRun) -> dict[str, Any]:
    output_json = _json(run.output_json)
    shadow_summary = _shadow_summary(output_json)
    shadow_events = _shadow_reasoner_events(output_json)
    shadow_diffs = _shadow_decision_diffs(output_json, shadow_events)
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "turn_id": str(run.turn_id) if run.turn_id else None,
        "run_type": run.run_type,
        "graph_name": run.graph_name,
        "model_provider": run.model_provider,
        "model_name": run.model_name,
        "status": run.status,
        "intent": _extract_intent(output_json),
        "assistant_message": output_json.get("assistant_message") if isinstance(output_json, dict) else None,
        "shadow_summary": shadow_summary,
        "shadow_enabled": bool(shadow_summary.get("enabled")) if isinstance(shadow_summary, dict) else False,
        "shadow_event_count": len(shadow_events),
        "shadow_mismatch_count": sum(1 for item in shadow_diffs if not item.get("matches")),
        "error_message": run.error_message,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def _admin_shadow_decision_diffs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    diffs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        deterministic = item.get("deterministic_decision") if isinstance(item.get("deterministic_decision"), dict) else {}
        shadow = item.get("shadow_decision") if isinstance(item.get("shadow_decision"), dict) else {}
        mismatch = not bool(item.get("matches", False))
        differences = item.get("differences") if isinstance(item.get("differences"), list) else []
        diffs.append(
            {
                "iteration": item.get("iteration"),
                "deterministic": deterministic,
                "shadow": shadow,
                "mismatch": mismatch,
                "mismatch_reason": ",".join(str(part) for part in differences) if differences else "same_decision",
                "schema_valid": item.get("shadow_status") == "success",
                "unsafe": False,
                "shadow_status": item.get("shadow_status"),
                "shadow_error": item.get("shadow_error"),
            }
        )
    return diffs


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _window(days: int) -> dict[str, datetime]:
    end = _utcnow()
    today_start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start - timedelta(days=days - 1)
    return {"start": start, "end": end, "today_start": today_start}


def _window_payload(window: dict[str, datetime]) -> dict[str, str]:
    return {key: value.isoformat() for key, value in window.items()}


INTERNAL_DEVICE_PREFIXES = (
    "eval-",
    "pytest",
    "admin-",
    "ops-",
    "manual-smoke",
    "smoke-",
    "test-",
    "debug-",
    "viewer-denied",
    "prompt-",
    "metrics-",
    "shadow-",
)


def _metric_scope_note(scope: str) -> str:
    if scope == "product":
        return "Live PostgreSQL metrics with eval/pytest/admin/smoke/internal device prefixes filtered out."
    return "Live PostgreSQL metrics across all persisted rows, including local tests and benchmark data."


def _product_user_conditions() -> list[Any]:
    internal_device = or_(*(User.device_uid.ilike(f"{prefix}%") for prefix in INTERNAL_DEVICE_PREFIXES))
    return [
        ~internal_device,
        or_(User.platform.is_(None), User.platform.not_in(["eval", "pytest", "test"])),
        or_(
            User.profile_json["namespace"].as_string().is_(None),
            User.profile_json["namespace"].as_string() != "pipi_eval",
        ),
    ]


def _apply_metric_scope(query: Any, model: type[Any], scope: str) -> Any:
    if scope != "product":
        return query
    conditions = _product_user_conditions()
    if model is User:
        return query.where(*conditions)
    if model is Conversation:
        return query.join(User, Conversation.user_id == User.id).where(*conditions)
    if model is Turn:
        return query.join(User, Turn.user_id == User.id).where(*conditions)
    if model is Question:
        return query.join(User, Question.user_id == User.id).where(*conditions)
    if model is RecommendationCard:
        return query.join(User, RecommendationCard.user_id == User.id).where(*conditions)
    if model is HelpCard:
        return query.join(User, HelpCard.owner_user_id == User.id).where(*conditions)
    if model is HelpAnswer:
        return query.join(User, HelpAnswer.answer_user_id == User.id).where(*conditions)
    if model is LightEvent:
        return query.join(User, LightEvent.user_id == User.id).where(*conditions)
    if model is AgentRun:
        return (
            query.join(Conversation, AgentRun.conversation_id == Conversation.id)
            .join(User, Conversation.user_id == User.id)
            .where(*conditions)
        )
    if model is ToolCall:
        return (
            query.join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
            .join(Conversation, AgentRun.conversation_id == Conversation.id)
            .join(User, Conversation.user_id == User.id)
            .where(*conditions)
        )
    if model is RetrievalRun:
        return (
            query.join(AgentRun, RetrievalRun.agent_run_id == AgentRun.id)
            .join(Conversation, AgentRun.conversation_id == Conversation.id)
            .join(User, Conversation.user_id == User.id)
            .where(*conditions)
        )
    return query


def _count_users(
    session: Session,
    *,
    scope: str,
    date_column: Any | None = None,
    start: datetime | None = None,
) -> int:
    query = select(func.count()).select_from(User)
    if date_column is not None and start is not None:
        query = query.where(date_column >= start)
    query = _apply_metric_scope(query, User, scope)
    return int(session.scalar(query) or 0)


def _count_turn_users_since(session: Session, start: datetime, *, scope: str) -> int:
    query = select(func.count(func.distinct(Turn.user_id))).select_from(Turn).where(
        Turn.created_at >= start,
        Turn.user_id.is_not(None),
    )
    query = _apply_metric_scope(query, Turn, scope)
    return int(session.scalar(query) or 0)


def _count_since(
    session: Session,
    model: type[Any],
    column: Any,
    start: datetime,
    *conditions: Any,
    scope: str = "all",
) -> int:
    query = select(func.count()).select_from(model).where(column >= start)
    if conditions:
        query = query.where(*conditions)
    query = _apply_metric_scope(query, model, scope)
    return int(session.scalar(query) or 0)


def _scoped_rows(session: Session, model: type[Any], column: Any, start: datetime, *, scope: str) -> list[Any]:
    query = select(model).where(column >= start)
    query = _apply_metric_scope(query, model, scope)
    return list(session.scalars(query).all())


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _outcome_counts(session: Session, start: datetime, *, scope: str) -> dict[str, int]:
    recommendation_cards = _count_since(
        session,
        RecommendationCard,
        RecommendationCard.created_at,
        start,
        scope=scope,
    )
    help_cards = _count_since(session, HelpCard, HelpCard.created_at, start, scope=scope)
    accepted_cards = _count_since(
        session,
        RecommendationCard,
        RecommendationCard.created_at,
        start,
        RecommendationCard.accepted_at.is_not(None),
        scope=scope,
    )
    final_cards = _count_since(
        session,
        HelpCard,
        HelpCard.created_at,
        start,
        HelpCard.final_recommendation_card_id.is_not(None),
        scope=scope,
    )
    light_events = _count_since(session, LightEvent, LightEvent.created_at, start, scope=scope)
    seen_light_events = _count_since(
        session,
        LightEvent,
        LightEvent.created_at,
        start,
        LightEvent.seen_at.is_not(None),
        scope=scope,
    )
    return {
        "recommendation_cards": recommendation_cards,
        "help_cards": help_cards,
        "accepted_cards": accepted_cards,
        "final_cards": final_cards,
        "light_events": light_events,
        "seen_light_events": seen_light_events,
    }


def _failure_counts(session: Session, start: datetime, *, scope: str) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    counts["failed_agent_runs"] = _count_since(
        session,
        AgentRun,
        AgentRun.created_at,
        start,
        AgentRun.status.not_in(["succeeded", "success", "completed"]),
        scope=scope,
    )
    counts["failed_tool_calls"] = _count_since(
        session,
        ToolCall,
        ToolCall.created_at,
        start,
        ToolCall.status.not_in(["succeeded", "success", "completed"]),
        scope=scope,
    )
    counts["failed_retrieval_runs"] = _count_since(
        session,
        RetrievalRun,
        RetrievalRun.created_at,
        start,
        RetrievalRun.status.not_in(["succeeded", "success", "completed"]),
        scope=scope,
    )
    counts["missing_image_cards"] = _count_since(
        session,
        RecommendationCard,
        RecommendationCard.created_at,
        start,
        or_(RecommendationCard.image_status == "missing", RecommendationCard.image_asset_id.is_(None)),
        scope=scope,
    )
    counts["low_confidence_cards"] = _count_since(
        session,
        RecommendationCard,
        RecommendationCard.created_at,
        start,
        RecommendationCard.confidence.is_not(None),
        RecommendationCard.confidence < 0.7,
        scope=scope,
    )
    counts["pending_or_blocked_images"] = int(
        session.scalar(
            select(func.count()).select_from(ImageAsset).where(
                or_(
                    ImageAsset.verified.is_(False),
                    ImageAsset.verification_status != "verified",
                    ImageAsset.displayable.is_(False),
                    ImageAsset.is_ai_generated.is_(True),
                )
            )
        )
        or 0
    )
    for run in _scoped_rows(session, AgentRun, AgentRun.created_at, start, scope=scope):
        output = _json(run.output_json)
        if _has_loop_event(output, "answer_gate_result", status_values={"rejected", "failed"}):
            counts["answer_gate_rejections"] += 1
        if _has_loop_event(output, "evaluator_result", status_values={"rejected", "failed"}):
            counts["evaluator_rejections"] += 1
        shadow_summary = _shadow_summary(output)
        if isinstance(shadow_summary, dict) and shadow_summary.get("enabled"):
            diffs = _shadow_decision_diffs(output, _shadow_reasoner_events(output))
            counts["shadow_mismatches"] += sum(1 for item in diffs if not item.get("matches"))
    return [
        {"key": key, "count": count}
        for key, count in sorted(counts.items())
        if count
    ]


def _has_loop_event(output_json: Any, event_name: str, *, status_values: set[str]) -> bool:
    loop_trace = output_json.get("loop_trace") if isinstance(output_json, dict) else None
    if not isinstance(loop_trace, list):
        return False
    for item in loop_trace:
        if not isinstance(item, dict) or item.get("event") != event_name:
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        status = str(data.get("status") or data.get("decision") or data.get("result") or "").lower()
        if status in status_values:
            return True
        if data.get("passed") is False or data.get("ok") is False:
            return True
    return False


def _daily_buckets(start: datetime, end: datetime) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end_day:
        key = cursor.date().isoformat()
        buckets[key] = {
            "date": key,
            "new_users": 0,
            "active_user_ids": set(),
            "turns": 0,
            "agent_runs": 0,
            "recommendation_cards": 0,
            "accepted_cards": 0,
            "help_cards": 0,
            "light_events": 0,
            "seen_light_events": 0,
        }
        cursor += timedelta(days=1)
    return buckets


def _bucket_key(value: datetime) -> str:
    return value.date().isoformat()


def _bucket_inc(buckets: dict[str, dict[str, Any]], timestamp: datetime | None, key: str) -> None:
    if timestamp is None:
        return
    bucket = buckets.get(_bucket_key(timestamp))
    if bucket is not None:
        bucket[key] = int(bucket.get(key) or 0) + 1


def _bucket_set_add(
    buckets: dict[str, dict[str, Any]],
    timestamp: datetime | None,
    key: str,
    value: str,
) -> None:
    if timestamp is None:
        return
    bucket = buckets.get(_bucket_key(timestamp))
    if bucket is not None:
        values = bucket.setdefault(key, set())
        values.add(value)


def _generated_content_tasks(session: Session, *, limit: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    images = session.scalars(
        select(ImageAsset)
        .where(
            or_(
                ImageAsset.verified.is_(False),
                ImageAsset.verification_status != "verified",
                ImageAsset.displayable.is_(False),
                ImageAsset.is_ai_generated.is_(True),
            )
        )
        .order_by(ImageAsset.updated_at.desc())
        .limit(limit)
    ).all()
    for image in images:
        tasks.append(
            _generated_task(
                task_type="image_review",
                priority=20 if image.is_ai_generated else 40,
                target_table="image_assets",
                target_record_id=str(image.id),
                title=f"审核图片资产 {image.source_domain or image.source_type}",
                reason="推荐卡图片必须 verified/displayable 且 is_ai_generated=false。",
                payload={
                    "url": image.url,
                    "verified": image.verified,
                    "verification_status": image.verification_status,
                    "displayable": image.displayable,
                    "is_ai_generated": image.is_ai_generated,
                },
            )
        )
    cards = session.scalars(
        select(RecommendationCard)
        .where(or_(RecommendationCard.image_status == "missing", RecommendationCard.image_asset_id.is_(None)))
        .order_by(RecommendationCard.updated_at.desc())
        .limit(limit)
    ).all()
    for card in cards:
        tasks.append(
            _generated_task(
                task_type="missing_card_image",
                priority=30,
                target_table="recommendation_cards",
                target_record_id=str(card.id),
                title=f"推荐卡缺少可信图片：{card.title}",
                reason="缺少 verified 非 AI 图片的卡片需要运营补证据或下线。",
                payload={"status": card.status, "image_status": card.image_status, "confidence": card.confidence},
            )
        )
    help_cards = session.scalars(
        select(HelpCard)
        .where(
            HelpCard.answer_count >= HelpCard.min_answers_required,
            HelpCard.final_recommendation_card_id.is_(None),
        )
        .order_by(HelpCard.updated_at.desc())
        .limit(limit)
    ).all()
    for help_card in help_cards:
        tasks.append(
            _generated_task(
                task_type="help_card_finalize_review",
                priority=50,
                target_table="help_cards",
                target_record_id=str(help_card.id),
                title=f"求一个可检查最终推荐：{help_card.title}",
                reason="答案数已达到最终推荐阈值，但尚未绑定最终推荐卡。",
                payload={"answer_count": help_card.answer_count, "min_answers_required": help_card.min_answers_required},
            )
        )
    return sorted(tasks, key=lambda item: (int(item["priority"]), item["task_type"]))[:limit]


def _generated_task(
    *,
    task_type: str,
    priority: int,
    target_table: str,
    target_record_id: str,
    title: str,
    reason: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": None,
        "task_type": task_type,
        "status": "open",
        "priority": priority,
        "target_table": target_table,
        "target_record_id": target_record_id,
        "title": title,
        "reason": reason,
        "payload_json": payload,
        "assigned_to": None,
        "resolved_at": None,
        "resolved_by": None,
        "created_at": None,
        "updated_at": None,
        "source": "generated",
    }


def _serialize_content_task(row: ContentReviewTask, *, source: str) -> dict[str, Any]:
    data = _row_dict(row)
    data["source"] = source
    return data


def _is_table_read_only(table_name: str, config: TableConfig, request: Request) -> bool:
    return bool(
        config.read_only
        or (table_name in RUNTIME_TABLES and not _settings(request).allow_admin_mutate_runtime_tables)
    )


def _table_metadata(table_name: str, config: TableConfig, session: Session, request: Request) -> dict[str, Any]:
    return {
        "name": table_name,
        "read_only": _is_table_read_only(table_name, config, request),
        "primary_key": _pk_column(config.model).key,
        "row_count": _table_count(session, config.model),
        "columns": [_column_metadata(column) for column in inspect(config.model).columns],
    }


def _column_metadata(column: Any) -> dict[str, Any]:
    return {
        "name": column.key,
        "type": column.type.__class__.__name__,
        "nullable": bool(column.nullable),
        "primary_key": bool(column.primary_key),
        "default": column.default is not None or column.server_default is not None,
    }


def _row_dict(row: Any) -> dict[str, Any]:
    return {column.key: _json(getattr(row, column.key)) for column in inspect(row.__class__).columns}


def _row_id(row: Any) -> str:
    return str(getattr(row, _pk_column(row.__class__).key))


def _get_row(session: Session, model: type[Any], row_id: str) -> Any:
    row = session.get(model, _pk_value(model, row_id))
    if row is None:
        raise HTTPException(status_code=404, detail="admin row not found")
    return row


def _get_uuid_row(session: Session, model: type[Any], row_id: str, detail: str) -> Any:
    row = session.get(model, _parse_uuid(row_id, "id"))
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


def _pk_column(model: type[Any]) -> Any:
    return inspect(model).primary_key[0]


def _pk_value(model: type[Any], raw: str) -> Any:
    column = _pk_column(model)
    if isinstance(column.type, PGUUID):
        return _parse_uuid(raw, column.key)
    return raw


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}") from exc


def _column_by_name(model: type[Any], column_name: str | None) -> Any:
    columns = {column.key: column for column in inspect(model).columns}
    if column_name is None or column_name not in columns:
        raise HTTPException(status_code=400, detail="unknown sort column")
    return columns[column_name]


def _default_sort_column(model: type[Any]) -> Any:
    columns = {column.key: column for column in inspect(model).columns}
    if "updated_at" in columns:
        return columns["updated_at"]
    if "created_at" in columns:
        return columns["created_at"]
    return _pk_column(model)


def _coerce_payload(model: type[Any], payload: dict[str, Any], *, for_insert: bool) -> dict[str, Any]:
    columns = {column.key: column for column in inspect(model).columns}
    values: dict[str, Any] = {}
    for key, raw_value in payload.items():
        column = columns.get(key)
        if column is None:
            raise HTTPException(status_code=400, detail=f"unknown column: {key}")
        if column.primary_key and not for_insert:
            continue
        values[key] = _coerce_value(column, raw_value)
    return values


def _validate_table_values(table_name: str, values: dict[str, Any]) -> None:
    if table_name == "content_review_tasks" and "target_table" in values:
        if values["target_table"] not in TABLES:
            raise HTTPException(status_code=400, detail="content review target_table is not allowlisted")


def _coerce_value(column: Any, value: Any) -> Any:
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, PGUUID):
        return _parse_uuid(str(value), column.key)
    if isinstance(column_type, JSONB):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"invalid JSON for {column.key}") from exc
        return value
    if isinstance(column_type, DateTime):
        if isinstance(value, datetime):
            return value
        normalized = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid datetime for {column.key}") from exc
    if isinstance(column_type, Boolean):
        if isinstance(value, bool):
            return value
        if str(value).lower() in {"true", "1", "yes"}:
            return True
        if str(value).lower() in {"false", "0", "no"}:
            return False
        raise HTTPException(status_code=400, detail=f"invalid boolean for {column.key}")
    if isinstance(column_type, Integer):
        return int(value)
    if isinstance(column_type, Float):
        return float(value)
    return str(value) if isinstance(column_type, (String, Text)) else value


def _search_condition(model: type[Any], q: str) -> Any:
    pattern = f"%{q.strip()}%"
    return or_(*(cast(column, String).ilike(pattern) for column in inspect(model).columns))


def _query_count(session: Session, query: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)


def _table_count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _pagination(*, page: int, page_size: int, total: int) -> dict[str, int | bool]:
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": page * page_size < total,
    }


def _write_audit(
    session: Session,
    *,
    request: Request,
    actor: str,
    action: str,
    table_name: str,
    target_record_id: str | None,
    request_json: dict[str, Any],
    before_json: dict[str, Any] | None,
    after_json: dict[str, Any] | None,
) -> None:
    session.add(
        AdminAuditLog(
            admin_actor=actor,
            action=action,
            target_table=table_name,
            target_record_id=target_record_id,
            request_path=str(request.url.path),
            request_json=_json(request_json),
            before_json=_json(before_json) if before_json is not None else None,
            after_json=_json(after_json) if after_json is not None else None,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    session.flush()


def _request_json(request: Request, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "method": request.method,
        "query": {
            key: ("<redacted>" if key.lower() in {"token", "authorization"} else value)
            for key, value in dict(request.query_params).items()
        },
    }
    if extra:
        data.update(extra)
    return data


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: Any) -> Any:
    return jsonable_encoder(value if value is not None else {})
