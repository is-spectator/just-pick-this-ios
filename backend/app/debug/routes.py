from __future__ import annotations

import uuid
from pathlib import Path
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db_session
from app.models import (
    AgentRun,
    Conversation,
    HelpAnswer,
    HelpCard,
    Question,
    RecommendationCard,
    RetrievalHit,
    RetrievalRun,
    ToolCall,
    Turn,
)
from app.services.runtime import serialize_card, serialize_help_card


router = APIRouter(prefix="/debug", tags=["debug"])

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_SESSIONS_HTML = _STATIC_DIR / "sessions.html"


@router.get("", include_in_schema=False)
def debug_root() -> RedirectResponse:
    return RedirectResponse(url="/debug/sessions")


@router.get("/sessions", response_class=HTMLResponse, include_in_schema=False)
def debug_sessions_page(request: Request) -> HTMLResponse:
    _require_debug_access(request)
    return HTMLResponse(_SESSIONS_HTML.read_text(encoding="utf-8"))


@router.get("/api/sessions")
def list_debug_sessions(
    request: Request,
    limit: int = Query(default=80, ge=1, le=250),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_debug_access(request)
    conversations = session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
    ).all()
    return {"sessions": [_serialize_conversation_summary(session, item) for item in conversations]}


@router.get("/api/sessions/{conversation_id}")
def get_debug_session(
    conversation_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _require_debug_access(request)
    try:
        conversation_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc

    conversation = session.get(Conversation, conversation_uuid)
    if conversation is None:
        raise HTTPException(status_code=404, detail="session not found")

    turns = session.scalars(
        select(Turn)
        .where(Turn.conversation_id == conversation.id)
        .order_by(Turn.turn_index.asc(), Turn.created_at.asc())
    ).all()
    agent_runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.conversation_id == conversation.id)
        .order_by(AgentRun.started_at.asc(), AgentRun.created_at.asc())
    ).all()
    questions = session.scalars(
        select(Question)
        .where(Question.conversation_id == conversation.id)
        .order_by(Question.created_at.asc())
    ).all()
    cards = session.scalars(
        select(RecommendationCard)
        .where(RecommendationCard.conversation_id == conversation.id)
        .order_by(RecommendationCard.created_at.asc())
    ).all()
    help_cards = session.scalars(
        select(HelpCard)
        .where(HelpCard.conversation_id == conversation.id)
        .order_by(HelpCard.created_at.asc())
    ).all()

    return {
        "session": _serialize_conversation_summary(session, conversation),
        "turns": [_serialize_turn(item) for item in turns],
        "traces": [_serialize_agent_run(session, item) for item in agent_runs],
        "questions": [_serialize_question(item) for item in questions],
        "cards": [serialize_card(item) for item in cards],
        "help_cards": [_serialize_help_card_with_answers(session, item) for item in help_cards],
    }


def _serialize_conversation_summary(session: Session, conversation: Conversation) -> dict[str, Any]:
    first_user_turn = session.scalar(
        select(Turn)
        .where(Turn.conversation_id == conversation.id, Turn.role == "user")
        .order_by(Turn.turn_index.asc())
        .limit(1)
    )
    latest_user_turn = session.scalar(
        select(Turn)
        .where(Turn.conversation_id == conversation.id, Turn.role == "user")
        .order_by(Turn.turn_index.desc())
        .limit(1)
    )
    latest_run = session.scalar(
        select(AgentRun)
        .where(AgentRun.conversation_id == conversation.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    latest_intent = _extract_intent(latest_run.output_json if latest_run else None)

    return {
        "id": str(conversation.id),
        "title": conversation.title or _short(first_user_turn.content if first_user_turn else "新 session"),
        "status": conversation.status,
        "user": {
            "id": str(conversation.user.id),
            "device_uid": conversation.user.device_uid,
            "display_name": conversation.user.display_name,
            "platform": conversation.user.platform,
            "app_version": conversation.user.app_version,
        },
        "created_at": _iso(conversation.created_at),
        "updated_at": _iso(conversation.updated_at),
        "latest_message": latest_user_turn.content if latest_user_turn else None,
        "latest_intent": latest_intent,
        "counts": {
            "turns": _count(session, Turn, Turn.conversation_id == conversation.id),
            "traces": _count(session, AgentRun, AgentRun.conversation_id == conversation.id),
            "tools": _count_joined_tools(session, conversation.id),
            "retrievals": _count_joined_retrievals(session, conversation.id),
            "cards": _count(session, RecommendationCard, RecommendationCard.conversation_id == conversation.id),
            "help_cards": _count(session, HelpCard, HelpCard.conversation_id == conversation.id),
        },
    }


def _serialize_turn(turn: Turn) -> dict[str, Any]:
    return {
        "id": str(turn.id),
        "role": turn.role,
        "content": turn.content,
        "turn_index": turn.turn_index,
        "status": turn.status,
        "created_at": _iso(turn.created_at),
        "content_json": _json(turn.content_json),
    }


def _serialize_agent_run(session: Session, run: AgentRun) -> dict[str, Any]:
    output_json = _json(run.output_json)
    shadow_events = _shadow_reasoner_events(output_json)
    retrieval_runs = session.scalars(
        select(RetrievalRun)
        .where(RetrievalRun.agent_run_id == run.id)
        .order_by(RetrievalRun.started_at.asc(), RetrievalRun.created_at.asc())
    ).all()
    tool_calls = session.scalars(
        select(ToolCall)
        .where(ToolCall.agent_run_id == run.id)
        .order_by(ToolCall.sequence_index.asc(), ToolCall.started_at.asc())
    ).all()
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
        "next_action": output_json.get("next_action") if isinstance(output_json, dict) else None,
        "assistant_message": output_json.get("assistant_message") if isinstance(output_json, dict) else None,
        "tool_call": output_json.get("tool_call") if isinstance(output_json, dict) else None,
        "tool_execution": output_json.get("tool_execution") if isinstance(output_json, dict) else None,
        "evidence_evaluation": output_json.get("evidence_evaluation") if isinstance(output_json, dict) else None,
        "shadow_summary": _shadow_summary(output_json),
        "shadow_events": shadow_events,
        "shadow_decision_diffs": _shadow_decision_diffs(output_json, shadow_events),
        "input_json": _json(run.input_json),
        "output_json": output_json,
        "metadata_json": _json(run.metadata_json),
        "error_message": run.error_message,
        "created_at": _iso(run.created_at),
        "updated_at": _iso(run.updated_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "graph_nodes": _graph_node_summary(output_json),
        "retrieval_runs": [_serialize_retrieval_run(session, item) for item in retrieval_runs],
        "tool_calls": [_serialize_tool_call(item) for item in tool_calls],
    }


def _serialize_retrieval_run(session: Session, run: RetrievalRun) -> dict[str, Any]:
    hits = session.scalars(
        select(RetrievalHit)
        .where(RetrievalHit.retrieval_run_id == run.id)
        .order_by(RetrievalHit.rank.asc())
    ).all()
    return {
        "id": str(run.id),
        "turn_id": str(run.turn_id) if run.turn_id else None,
        "query": run.query,
        "source": run.source,
        "status": run.status,
        "top_k": run.top_k,
        "filters_json": _json(run.filters_json),
        "metadata_json": _json(run.metadata_json),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "hits": [_serialize_retrieval_hit(item) for item in hits],
    }


def _serialize_retrieval_hit(hit: RetrievalHit) -> dict[str, Any]:
    return {
        "id": str(hit.id),
        "rank": hit.rank,
        "score": hit.score,
        "source_type": hit.source_type,
        "source_id": hit.source_id,
        "source_uri": hit.source_uri,
        "title": hit.title,
        "snippet": hit.snippet,
        "payload_json": _json(hit.payload_json),
        "created_at": _iso(hit.created_at),
    }


def _serialize_tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "turn_id": str(call.turn_id) if call.turn_id else None,
        "tool_name": call.tool_name,
        "status": call.status,
        "sequence_index": call.sequence_index,
        "arguments_json": _json(call.arguments_json),
        "result_json": _json(call.result_json),
        "error_message": call.error_message,
        "created_at": _iso(call.created_at),
        "updated_at": _iso(call.updated_at),
        "started_at": _iso(call.started_at),
        "finished_at": _iso(call.finished_at),
    }


def _serialize_question(question: Question) -> dict[str, Any]:
    return {
        "id": str(question.id),
        "turn_id": str(question.turn_id) if question.turn_id else None,
        "raw_text": question.raw_text,
        "normalized_text": question.normalized_text,
        "status": question.status,
        "current_recommendation_card_id": str(question.current_recommendation_card_id)
        if question.current_recommendation_card_id
        else None,
        "current_help_card_id": str(question.current_help_card_id)
        if question.current_help_card_id
        else None,
        "context_json": _json(question.context_json),
        "created_at": _iso(question.created_at),
        "updated_at": _iso(question.updated_at),
    }


def _serialize_help_card_with_answers(session: Session, help_card: HelpCard) -> dict[str, Any]:
    data = serialize_help_card(help_card)
    answers = session.scalars(
        select(HelpAnswer)
        .where(HelpAnswer.help_card_id == help_card.id)
        .order_by(HelpAnswer.created_at.asc())
    ).all()
    data["answers"] = [
        {
            "id": str(answer.id),
            "answer_user_id": str(answer.answer_user_id) if answer.answer_user_id else None,
            "raw_text": answer.raw_text,
            "evidence_json": _json(answer.evidence_json),
            "created_at": _iso(answer.created_at),
        }
        for answer in answers
    ]
    return data


def _graph_node_summary(output_json: Any) -> list[dict[str, Any]]:
    if not isinstance(output_json, dict):
        return []
    loop_trace = output_json.get("loop_trace")
    if isinstance(loop_trace, list) and loop_trace:
        context_pack = next(
            (
                item.get("data")
                for item in loop_trace
                if isinstance(item, dict) and item.get("event") == "context_pack"
            ),
            None,
        )
        tool_calls = [
            item.get("data", {}).get("tool_name")
            for item in loop_trace
            if isinstance(item, dict) and item.get("event") == "tool_call"
        ]
        nodes: list[tuple[str, Any]] = [
            ("persist_turn", {"user_turn_id": output_json.get("user_turn_id")}),
            ("input_gate", output_json.get("input_gate_result")),
            ("build_context", context_pack or output_json.get("context")),
            (
                "run_pipi_loop",
                {
                    "event_count": len(loop_trace),
                    "tool_calls": [name for name in tool_calls if name],
                    "finish_reason": output_json.get("loop", {}).get("finish_reason")
                    if isinstance(output_json.get("loop"), dict)
                    else None,
                },
            ),
            ("persist_response", {"assistant_message": output_json.get("assistant_message")}),
        ]
        return [{"name": name, "data": _json(data)} for name, data in nodes if data not in (None, {})]

    nodes: list[tuple[str, Any]] = [
        ("persist_turn", {"user_turn_id": output_json.get("user_turn_id")}),
        ("build_context", output_json.get("context")),
        ("rewrite_query", output_json.get("query_rewrite")),
        ("classify_intent", {"intent": output_json.get("intent")}),
        ("retrieve_knowledge", output_json.get("retrieval_run")),
        ("evaluate_evidence", output_json.get("evidence_evaluation")),
        (
            "decide_next_action",
            {"next_action": output_json.get("next_action"), "tool_call": output_json.get("tool_call")},
        ),
        ("execute_tool", output_json.get("tool_execution")),
        ("respond", {"assistant_message": output_json.get("assistant_message")}),
    ]
    return [{"name": name, "data": _json(data)} for name, data in nodes if data not in (None, {})]


def _shadow_summary(output_json: Any) -> Any:
    if not isinstance(output_json, dict):
        return None
    summary = output_json.get("shadow_summary")
    if summary is not None:
        return _json(summary)
    shadow_llm = output_json.get("shadow_llm")
    if isinstance(shadow_llm, dict) and shadow_llm.get("summary") is not None:
        return _json(shadow_llm.get("summary"))
    return None


def _shadow_reasoner_events(output_json: Any) -> list[dict[str, Any]]:
    if not isinstance(output_json, dict):
        return []
    loop_trace = output_json.get("loop_trace")
    if not isinstance(loop_trace, list):
        return []
    return [
        _json(event)
        for event in loop_trace
        if isinstance(event, dict) and event.get("event") == "shadow_reasoner_result"
    ]


def _shadow_decision_diffs(
    output_json: Any,
    shadow_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(output_json, dict):
        return []
    loop_trace = output_json.get("loop_trace")
    if not isinstance(loop_trace, list):
        return []

    deterministic_events = [
        event
        for event in loop_trace
        if isinstance(event, dict) and event.get("event") == "reasoner_decision"
    ]
    shadow_items = shadow_events if shadow_events is not None else _shadow_reasoner_events(output_json)
    if not shadow_items:
        return []

    unused_shadow_indexes = set(range(len(shadow_items)))
    diffs: list[dict[str, Any]] = []

    for index, deterministic_event in enumerate(deterministic_events):
        deterministic_iteration = _event_iteration(deterministic_event) or index + 1
        shadow_index = _matching_shadow_index(
            shadow_items,
            unused_shadow_indexes,
            deterministic_iteration,
            fallback_index=index,
        )
        shadow_event = shadow_items[shadow_index] if shadow_index is not None else None
        if shadow_index is not None:
            unused_shadow_indexes.discard(shadow_index)
        diffs.append(_shadow_decision_diff(deterministic_iteration, deterministic_event, shadow_event))

    for shadow_index in sorted(unused_shadow_indexes):
        shadow_event = shadow_items[shadow_index]
        shadow_iteration = _event_iteration(shadow_event) or len(diffs) + 1
        diffs.append(_shadow_decision_diff(shadow_iteration, None, shadow_event))

    return diffs


def _matching_shadow_index(
    shadow_events: list[dict[str, Any]],
    unused_indexes: set[int],
    iteration: int,
    *,
    fallback_index: int,
) -> int | None:
    for index in sorted(unused_indexes):
        if _event_iteration(shadow_events[index]) == iteration:
            return index
    if fallback_index in unused_indexes:
        return fallback_index
    return None


def _shadow_decision_diff(
    iteration: int,
    deterministic_event: dict[str, Any] | None,
    shadow_event: dict[str, Any] | None,
) -> dict[str, Any]:
    shadow_payload = _event_payload(shadow_event)
    deterministic_payload = _event_payload(deterministic_event)
    if not deterministic_payload and isinstance(shadow_payload.get("deterministic_decision"), dict):
        deterministic_payload = shadow_payload["deterministic_decision"]
    deterministic_decision = _decision_signature(deterministic_payload)
    shadow_decision = _decision_signature(_shadow_decision_payload(shadow_payload))
    differences = _decision_differences(deterministic_decision, shadow_decision)
    if deterministic_event is None and not deterministic_decision:
        differences = ["deterministic_missing", *differences]
    if shadow_event is None:
        differences = ["shadow_missing", *differences]

    return {
        "iteration": iteration,
        "matches": not differences,
        "differences": differences,
        "deterministic_decision": deterministic_decision,
        "shadow_decision": shadow_decision,
        "shadow_status": shadow_payload.get("status") if isinstance(shadow_payload, dict) else None,
        "shadow_error": _shadow_error(shadow_payload),
    }


def _event_iteration(event: dict[str, Any] | None) -> int | None:
    if not isinstance(event, dict):
        return None
    for candidate in (event.get("iteration"), _event_payload(event).get("iteration")):
        try:
            return int(candidate) if candidate is not None else None
        except (TypeError, ValueError):
            continue
    return None


def _event_payload(event: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    for key in ("data", "payload"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _shadow_decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw_shadow_result = payload.get("raw_shadow_result")
    if isinstance(raw_shadow_result, dict):
        raw_decision = _shadow_decision_payload(raw_shadow_result)
        if raw_decision:
            return raw_decision
    for key in (
        "normalized_decision",
        "shadow_decision",
        "decision_json",
        "shadow_reasoner_result",
        "llm_decision",
        "decision",
        "result",
        "output",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _shadow_error(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("error", "error_message"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    raw_shadow_result = payload.get("raw_shadow_result")
    if isinstance(raw_shadow_result, dict):
        return _shadow_error(raw_shadow_result)
    return None


def _decision_signature(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {}

    nested_tool_call = payload.get("tool_call") if isinstance(payload.get("tool_call"), dict) else {}
    tool_args = payload.get("tool_args")
    if tool_args is None:
        tool_args = payload.get("arguments")
    if tool_args is None and isinstance(nested_tool_call, dict):
        tool_args = nested_tool_call.get("tool_args") or nested_tool_call.get("arguments")

    signature = {
        "type": payload.get("type") or payload.get("decision_type") or payload.get("kind"),
        "next_action": payload.get("next_action") or payload.get("action"),
        "tool_name": payload.get("tool_name")
        or payload.get("name")
        or (nested_tool_call.get("tool_name") if isinstance(nested_tool_call, dict) else None)
        or (nested_tool_call.get("name") if isinstance(nested_tool_call, dict) else None),
        "tool_args": _json(tool_args) if tool_args is not None else None,
        "message": payload.get("message") or payload.get("assistant_message") or payload.get("answer"),
    }
    return {key: value for key, value in signature.items() if value is not None}


def _decision_differences(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    if not left and not right:
        return []
    keys = ("type", "next_action", "tool_name", "tool_args", "message")
    return [key for key in keys if left.get(key) != right.get(key)]


def _extract_intent(output_json: Any) -> str | None:
    if not isinstance(output_json, dict):
        return None
    intent = output_json.get("intent")
    return str(intent) if intent is not None else None


def _count(session: Session, model: type[Any], *where: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _count_joined_tools(session: Session, conversation_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count(ToolCall.id))
            .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_id)
        )
        or 0
    )


def _count_joined_retrievals(session: Session, conversation_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count(RetrievalRun.id))
            .join(AgentRun, RetrievalRun.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_id)
        )
        or 0
    )


def _short(value: str, max_length: int = 42) -> str:
    stripped = " ".join(value.split())
    if len(stripped) <= max_length:
        return stripped
    return f"{stripped[:max_length - 1]}…"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: Any) -> Any:
    return jsonable_encoder(value if value is not None else {})


def _require_debug_access(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None) or get_settings()
    configured = settings.debug_dashboard_token
    if configured is None:
        raise HTTPException(status_code=503, detail="DEBUG_DASHBOARD_TOKEN is not configured")

    expected = configured.get_secret_value()
    authorization = request.headers.get("authorization") or ""
    bearer = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not bearer or not compare_digest(bearer, expected):
        raise HTTPException(status_code=401, detail="debug dashboard token required")
