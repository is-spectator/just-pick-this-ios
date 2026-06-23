from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.config import get_settings
from app.models import (
    AgentRun,
    Conversation,
    HelpAnswer,
    HelpCard,
    ImageAsset,
    Intent,
    IntentAnswer,
    LightEvent,
    Question,
    RecommendationCard,
    RetrievalHit,
    RetrievalRun,
    ToolCall,
    Turn,
    User,
    UserBehaviorEvent,
)
from app.services.runtime import (
    create_question_for_turn,
    create_tool_call,
    create_turn,
    ensure_user,
    finish_tool_call,
    get_or_create_conversation,
    serialize_image,
    session_scope,
    utcnow,
)


EVAL_NAMESPACE = "pipi_eval"
PACK_ID = "food_beijing_onsite_v1"
CARD_VERSION = "onsite_food_beijing_v1"
AREA_INTENT_KEY = "eval.food_beijing_onsite_v1.area.sanlitun_sichuan"
VENUE_INTENT_KEY = "eval.food_beijing_onsite_v1.venue.sijiminfu_ordering"


def ensure_eval_mode() -> None:
    if not get_settings().pipi_eval_mode:
        raise HTTPException(status_code=404, detail="eval_mode_disabled")


def reset_eval(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_eval_mode()
    with session_scope() as session:
        eval_users = [
            user
            for user in session.scalars(select(User)).all()
            if user.device_uid.startswith("eval-")
            or (user.profile_json or {}).get("namespace") == EVAL_NAMESPACE
        ]
        eval_user_ids = {user.id for user in eval_users}
        eval_conversations = [
            conversation
            for conversation in session.scalars(select(Conversation)).all()
            if conversation.user_id in eval_user_ids
            or (conversation.metadata_json or {}).get("namespace") == EVAL_NAMESPACE
        ]
        eval_conversation_ids = {conversation.id for conversation in eval_conversations}
        eval_turn_ids = set(
            session.scalars(select(Turn.id).where(Turn.conversation_id.in_(eval_conversation_ids))).all()
        )
        eval_agent_run_ids = set(
            session.scalars(
                select(AgentRun.id).where(AgentRun.conversation_id.in_(eval_conversation_ids))
            ).all()
        )
        eval_retrieval_run_ids = set(
            session.scalars(
                select(RetrievalRun.id).where(RetrievalRun.agent_run_id.in_(eval_agent_run_ids))
            ).all()
        )
        eval_question_ids = set(
            session.scalars(
                select(Question.id).where(Question.conversation_id.in_(eval_conversation_ids))
            ).all()
        )
        eval_help_card_ids = set(
            session.scalars(select(HelpCard.id).where(HelpCard.question_id.in_(eval_question_ids))).all()
        )
        eval_card_ids = set(
            session.scalars(
                select(RecommendationCard.id).where(
                    RecommendationCard.question_id.in_(eval_question_ids)
                )
            ).all()
        )

        behavior_event_filters = []
        if eval_conversation_ids:
            behavior_event_filters.append(UserBehaviorEvent.conversation_id.in_(eval_conversation_ids))
        if eval_user_ids:
            behavior_event_filters.append(UserBehaviorEvent.user_id.in_(eval_user_ids))
        eval_behavior_event_ids = (
            set(
                session.scalars(
                    select(UserBehaviorEvent.id).where(or_(*behavior_event_filters))
                ).all()
            )
            if behavior_event_filters
            else set()
        )

        for model, ids in (
            (
                UserBehaviorEvent,
                eval_behavior_event_ids,
            ),
            (HelpAnswer, _ids_for(HelpAnswer.help_card_id, eval_help_card_ids, session, HelpAnswer.id)),
            (LightEvent, _ids_for(LightEvent.conversation_id, eval_conversation_ids, session, LightEvent.id)),
            (RetrievalHit, _ids_for(RetrievalHit.retrieval_run_id, eval_retrieval_run_ids, session, RetrievalHit.id)),
            (ToolCall, _ids_for(ToolCall.agent_run_id, eval_agent_run_ids, session, ToolCall.id)),
            (RetrievalRun, eval_retrieval_run_ids),
            (HelpCard, eval_help_card_ids),
            (RecommendationCard, eval_card_ids),
            (Question, eval_question_ids),
            (AgentRun, eval_agent_run_ids),
            (Turn, eval_turn_ids),
            (Conversation, eval_conversation_ids),
            (User, eval_user_ids),
        ):
            for item in session.scalars(select(model).where(model.id.in_(ids))).all():
                session.delete(item)
            if model is Conversation and ids:
                # Flush deleted conversations before deleting eval users. Without
                # this, SQLAlchemy may try to null Conversation.user_id while
                # cascading user cleanup, which violates the not-null FK.
                session.flush()

        for answer in session.scalars(select(IntentAnswer)).all():
            evidence = answer.evidence_json or {}
            if evidence.get("namespace") == EVAL_NAMESPACE or answer.intent_key in {
                AREA_INTENT_KEY,
                VENUE_INTENT_KEY,
            }:
                session.delete(answer)
        for intent in session.scalars(select(Intent)).all():
            if intent.key in {AREA_INTENT_KEY, VENUE_INTENT_KEY}:
                session.delete(intent)
        for image in session.scalars(select(ImageAsset)).all():
            if (image.metadata_json or {}).get("namespace") == EVAL_NAMESPACE:
                session.delete(image)

        return {"ok": True, "reset_at": utcnow()}


def _ids_for(column: Any, values: set[uuid.UUID], session: Any, id_column: Any) -> set[uuid.UUID]:
    if not values:
        return set()
    return set(session.scalars(select(id_column).where(column.in_(values))).all())


def seed_food_beijing_onsite_v1(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_eval_mode()
    del payload
    with session_scope() as session:
        area_intent = _upsert_intent(
            session,
            key=AREA_INTENT_KEY,
            name="三里屯川菜现场选店",
            description="Area food intent for Sanlitun Sichuan food in eval mode.",
            examples=["我到了北京三里屯，有什么好吃的川菜么", "三里屯川菜就选一个"],
        )
        venue_intent = _upsert_intent(
            session,
            key=VENUE_INTENT_KEY,
            name="四季民福故宫店现场点菜",
            description="Venue ordering bundle intent for Siji Minfu Palace Museum branch.",
            examples=["我在四季民福故宫店，第一次来怎么点菜", "四季民福点菜选一个"],
        )
        _upsert_intent_answer(
            session,
            intent=area_intent,
            source_type="area_intent_answer",
            title="三里屯川菜馆",
            summary="在三里屯想吃川菜，选一家近、稳、适合现场落座的店。",
            decision_factor="三里屯现场吃川菜，近一点、口味稳定，比临时刷榜更稳。",
            constraints={
                "location_state": "in_area",
                "target_type": "restaurant",
                "area_anchor": "三里屯",
                "cuisine": "川菜",
            },
            confidence=0.86,
        )
        _upsert_intent_answer(
            session,
            intent=venue_intent,
            source_type="ordering_bundle_answer",
            title="烤鸭 + 清爽配菜 + 甜品",
            summary="第一次来四季民福，先吃招牌烤鸭，再配一个清爽菜和甜品。",
            decision_factor="第一次来四季民福，先吃招牌，口味最稳。",
            constraints={
                "location_state": "in_venue",
                "target_type": "ordering_bundle",
                "venue": "四季民福故宫店",
                "party_size": 2,
            },
            confidence=0.92,
        )
        return {
            "ok": True,
            "pack_id": PACK_ID,
            "seeded": {
                "area_anchors": 1,
                "venues": 1,
                "area_intent_answers": 1,
                "ordering_bundle_answers": 1,
            },
        }


def seed_negative_cases() -> dict[str, Any]:
    ensure_eval_mode()
    return {"ok": True}


def seed_status() -> dict[str, Any]:
    ensure_eval_mode()
    with session_scope() as session:
        area_answer = _find_answer(session, AREA_INTENT_KEY, "area_intent_answer")
        venue_answer = _find_answer(session, VENUE_INTENT_KEY, "ordering_bundle_answer")
        last_seeded = None
        for answer in (area_answer, venue_answer):
            if answer is not None and (last_seeded is None or answer.updated_at > last_seeded):
                last_seeded = answer.updated_at
        return {
            "pack_id": PACK_ID,
            "area_anchor_count": 1 if session.scalar(select(Intent).where(Intent.key == AREA_INTENT_KEY)) else 0,
            "venue_count": 1 if session.scalar(select(Intent).where(Intent.key == VENUE_INTENT_KEY)) else 0,
            "area_intent_answer_count": 1 if area_answer else 0,
            "ordering_bundle_answer_count": 1 if venue_answer else 0,
            "last_seeded_at": last_seeded,
        }


def run_eval_chat_turn(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_eval_mode()
    include_debug = bool((payload.get("client_context") or {}).get("include_debug"))
    with session_scope() as session:
        user = ensure_user(
            session,
            device_uid=payload.get("device_id") or payload.get("device_uid"),
            user_id=payload.get("user_id"),
            platform="eval",
            app_version=(payload.get("client_context") or {}).get("app_version"),
        )
        user.profile_json = {
            **(user.profile_json or {}),
            "namespace": EVAL_NAMESPACE,
            "eval_run_id": (payload.get("client_context") or {}).get("eval_run_id"),
        }
        conversation = get_or_create_conversation(
            session,
            user=user,
            conversation_id=payload.get("conversation_id"),
            always_create=True,
        )
        conversation.metadata_json = {
            **(conversation.metadata_json or {}),
            "namespace": EVAL_NAMESPACE,
            "pack_id": PACK_ID,
            "eval_run_id": (payload.get("client_context") or {}).get("eval_run_id"),
        }
        if not conversation.title:
            conversation.title = payload["message"][:80]
        user_turn = create_turn(
            session,
            conversation=conversation,
            user=user,
            role="user",
            content=payload["message"],
            content_json={
                "metadata": payload.get("metadata", {}),
                "client_context": payload.get("client_context", {}),
                "client_turn_id": payload.get("client_turn_id"),
            },
        )
        question = create_question_for_turn(session, conversation=conversation, user=user, turn=user_turn)
        question.context_json = {"namespace": EVAL_NAMESPACE, "pack_id": PACK_ID}

        selected = _select_seeded_answer(session, payload["message"])
        location_state = selected["location_state"]
        source_answer = selected.get("answer")
        source_answer_type = selected.get("source_answer_type")
        confidence = float(selected.get("confidence") or 0.0)

        agent_run = AgentRun(
            conversation_id=conversation.id,
            turn_id=user_turn.id,
            run_type="pipi_eval_chat",
            graph_name="PipiEvalGraph",
            model_provider="deterministic",
            model_name="pipi-eval-deterministic-v1",
            status="running",
            input_json={
                "message": payload["message"],
                "metadata": payload.get("metadata", {}),
                "client_context": payload.get("client_context", {}),
            },
            metadata_json={"namespace": EVAL_NAMESPACE, "pack_id": PACK_ID},
        )
        session.add(agent_run)
        session.flush()

        retrieval_run = _create_eval_retrieval_run(
            session,
            agent_run=agent_run,
            turn=user_turn,
            message=payload["message"],
            source_answer=source_answer,
            source_answer_type=source_answer_type,
            confidence=confidence,
        )

        if source_answer is not None:
            result = _create_eval_recommendation(
                session,
                user=user,
                conversation=conversation,
                question=question,
                user_turn=user_turn,
                agent_run=agent_run,
                retrieval_run=retrieval_run,
                answer=source_answer,
                source_answer_type=source_answer_type or "area_intent_answer",
                location_state=location_state,
            )
            assistant_message = "就选这个。"
            selected_tool = "create_recommendation_card"
            response_kind = "recommendation_card"
        else:
            result = _create_eval_help_card(
                session,
                user=user,
                conversation=conversation,
                question=question,
                user_turn=user_turn,
                agent_run=agent_run,
                location_state=location_state,
            )
            assistant_message = "这题证据不够稳，先帮你求一个。"
            selected_tool = "draft_help_card"
            response_kind = "help_card_draft"

        assistant_turn = create_turn(
            session,
            conversation=conversation,
            user=None,
            role="assistant",
            content=assistant_message,
            content_json={"eval_graph_state": result["debug_base"]},
        )

        debug_base = {
            **result["debug_base"],
            "enabled": True,
            "selected_tool": selected_tool,
            "location_state": location_state,
            "intent_key": selected.get("intent_key"),
            "source_answer_type": source_answer_type,
            "confidence": confidence,
            "retrieval_run_id": str(retrieval_run.id),
            "agent_run_id": str(agent_run.id),
            "tool_call_ids": result["tool_call_ids"],
        }
        agent_run.status = "succeeded"
        agent_run.output_json = {
            **debug_base,
            "ui_events": result["ui_events"],
            "data": result["data"],
        }
        agent_run.finished_at = utcnow()

        response: dict[str, Any] = {
            "conversation_id": str(conversation.id),
            "turn_id": str(user_turn.id),
            "user_turn_id": str(user_turn.id),
            "assistant_turn_id": str(assistant_turn.id),
            "assistant_message": assistant_message,
            "response_kind": response_kind,
            "location_state": location_state,
            "ui_events": result["ui_events"],
            "data": result["data"],
            "cards": result.get("cards", []),
            "help_cards": result.get("help_cards", []),
            "light_events": [],
            "tool_calls": result["tool_calls"],
            "metadata": {
                "intent": {"key": selected.get("intent_key"), "type": "decision_request"},
                "agent_run_id": str(agent_run.id),
                "retrieval_run_id": str(retrieval_run.id),
                "retrieval_run": _serialize_retrieval_run(retrieval_run),
                "selected_tool": selected_tool,
                "runtime_path": "eval_bypass",
                "benchmark": {
                    "suite_id": (payload.get("client_context") or {}).get("benchmark_suite_id"),
                    "case_id": (payload.get("client_context") or {}).get("benchmark_case_id"),
                    "eval_run_id": (payload.get("client_context") or {}).get("eval_run_id"),
                },
            },
        }
        if include_debug:
            response["debug"] = debug_base
        return response


def trace_by_conversation(conversation_id: str) -> dict[str, Any]:
    ensure_eval_mode()
    conversation_uuid = uuid.UUID(conversation_id)
    with session_scope() as session:
        turns = session.scalars(
            select(Turn).where(Turn.conversation_id == conversation_uuid).order_by(Turn.turn_index.asc())
        ).all()
        agent_runs = session.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation_uuid)
            .order_by(AgentRun.created_at.asc())
        ).all()
        agent_run_ids = [run.id for run in agent_runs]
        tool_calls = session.scalars(
            select(ToolCall).where(ToolCall.agent_run_id.in_(agent_run_ids)).order_by(ToolCall.created_at.asc())
        ).all()
        retrieval_runs = session.scalars(
            select(RetrievalRun)
            .where(RetrievalRun.agent_run_id.in_(agent_run_ids))
            .order_by(RetrievalRun.created_at.asc())
        ).all()
        retrieval_run_ids = [run.id for run in retrieval_runs]
        retrieval_hits = session.scalars(
            select(RetrievalHit)
            .where(RetrievalHit.retrieval_run_id.in_(retrieval_run_ids))
            .order_by(RetrievalHit.created_at.asc())
        ).all()
        return {
            "conversation_id": conversation_id,
            "turns": [_serialize_turn(turn) for turn in turns],
            "agent_runs": [_serialize_agent_run(run) for run in agent_runs],
            "tool_calls": [_serialize_tool_call(call) for call in tool_calls],
            "retrieval_runs": [_serialize_retrieval_run(run) for run in retrieval_runs],
            "retrieval_hits": [_serialize_retrieval_hit(hit) for hit in retrieval_hits],
        }


def trace_by_turn(turn_id: str) -> dict[str, Any]:
    ensure_eval_mode()
    turn_uuid = uuid.UUID(turn_id)
    with session_scope() as session:
        agent_run = session.scalar(
            select(AgentRun).where(AgentRun.turn_id == turn_uuid).order_by(AgentRun.created_at.desc())
        )
        if agent_run is None:
            return {
                "turn_id": turn_id,
                "agent_run": None,
                "tool_calls": [],
                "retrieval_run": None,
                "retrieval_hits": [],
            }
        tool_calls = session.scalars(
            select(ToolCall).where(ToolCall.agent_run_id == agent_run.id).order_by(ToolCall.created_at.asc())
        ).all()
        retrieval_run = session.scalar(
            select(RetrievalRun)
            .where(RetrievalRun.agent_run_id == agent_run.id)
            .order_by(RetrievalRun.created_at.desc())
        )
        retrieval_hits = []
        if retrieval_run is not None:
            retrieval_hits = session.scalars(
                select(RetrievalHit)
                .where(RetrievalHit.retrieval_run_id == retrieval_run.id)
                .order_by(RetrievalHit.rank.asc())
            ).all()
        return {
            "turn_id": turn_id,
            "agent_run": _serialize_agent_run(agent_run),
            "tool_calls": [_serialize_tool_call(call) for call in tool_calls],
            "retrieval_run": _serialize_retrieval_run(retrieval_run) if retrieval_run else None,
            "retrieval_hits": [_serialize_retrieval_hit(hit) for hit in retrieval_hits],
        }


def should_use_eval_runtime(payload: dict[str, Any]) -> bool:
    settings = get_settings()
    if not settings.allow_eval_bypass:
        return False
    if not settings.pipi_eval_mode:
        return False
    if not _has_explicit_eval_bypass_opt_in(payload):
        return False
    client_context = payload.get("client_context") or {}
    device_uid = str(payload.get("device_id") or payload.get("device_uid") or "")
    return (
        client_context.get("source") == "pipi-eval-lab"
        or device_uid.startswith("eval-")
        or payload.get("platform") == "eval"
    )


def _has_explicit_eval_bypass_opt_in(payload: dict[str, Any]) -> bool:
    client_context = payload.get("client_context") or {}
    metadata = payload.get("metadata") or {}
    headers = metadata.get("headers") if isinstance(metadata.get("headers"), dict) else {}
    return any(
        _truthy_flag(value)
        for value in (
            client_context.get("pipi_eval_mode"),
            client_context.get("x_pipi_eval_mode"),
            metadata.get("pipi_eval_mode"),
            headers.get("x-pipi-eval-mode"),
            headers.get("X-Pipi-Eval-Mode"),
        )
    )


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def serialize_eval_card(card: RecommendationCard) -> dict[str, Any]:
    payload = card.payload_json or {}
    return {
        "id": str(card.id),
        "type": "recommendation_card",
        "version": payload.get("version", CARD_VERSION),
        "target_type": payload.get("target_type", "restaurant"),
        "title": card.title,
        "subtitle": card.subtitle,
        "decision_factor": payload.get("decision_factor", {"text": card.reason}),
        "image": serialize_image(card.image_asset),
        "provenance": payload.get("provenance", {}),
        "ui": payload.get("ui", {}),
        "status": card.status,
    }


def serialize_eval_help_card(help_card: HelpCard) -> dict[str, Any]:
    payload = help_card.payload_json or {}
    answer_stats = dict(payload.get("answer_stats") or {})
    answer_stats["count"] = help_card.answer_count
    answer_stats["min_required"] = help_card.min_answers_required
    return {
        "id": str(help_card.id),
        "type": "help_card",
        "version": payload.get("version", CARD_VERSION),
        "status": help_card.status,
        "title": help_card.title,
        "prompt": help_card.prompt,
        "location_state": payload.get("location_state", "unknown"),
        "context": payload.get("context", {}),
        "wants": payload.get("wants", []),
        "avoids": payload.get("avoids", []),
        "constraints": payload.get("constraints", []),
        "reward": payload.get("reward", {"label": "+10", "value": 10}),
        "answer_stats": answer_stats,
        "revision": payload.get("revision", 1),
        "metadata": {
            "owner_user_id": str(help_card.owner_user_id),
            "question_id": str(help_card.question_id),
        },
        "created_at": _iso(help_card.created_at),
    }


def _upsert_intent(
    session: Any,
    *,
    key: str,
    name: str,
    description: str,
    examples: list[str],
) -> Intent:
    intent = session.scalar(select(Intent).where(Intent.key == key))
    if intent is None:
        intent = Intent(key=key, name=name, description=description)
        session.add(intent)
    intent.name = name
    intent.description = description
    intent.examples_json = [{"text": example} for example in examples]
    intent.is_active = True
    session.flush()
    return intent


def _upsert_intent_answer(
    session: Any,
    *,
    intent: Intent,
    source_type: str,
    title: str,
    summary: str,
    decision_factor: str,
    constraints: dict[str, Any],
    confidence: float,
) -> IntentAnswer:
    answer = _find_answer(session, intent.key, source_type)
    if answer is None:
        answer = IntentAnswer(intent_id=intent.id, source_type=source_type, answer_text=summary)
        session.add(answer)
    answer.intent_id = intent.id
    answer.intent_key = intent.key
    answer.intent_text = intent.name
    answer.answer_title = title
    answer.answer_summary = summary
    answer.answer_text = summary
    answer.constraints_json = constraints
    answer.source_type = source_type
    answer.source_ref_id = f"{PACK_ID}:{source_type}"
    answer.confidence = confidence
    answer.last_used_at = utcnow()
    answer.tags_json = [PACK_ID, constraints["location_state"], constraints["target_type"]]
    answer.evidence_json = {
        "namespace": EVAL_NAMESPACE,
        "pack_id": PACK_ID,
        "version": CARD_VERSION,
        "approved": True,
        "decision_factor": {"text": decision_factor, "key": source_type},
        "target_type": constraints["target_type"],
        "location_state": constraints["location_state"],
        "provenance": {
            "source": "eval_seed",
            "source_answer_type": source_type,
            "confidence": confidence,
        },
        "ui": {"density": "single_card"},
    }
    answer.is_active = True
    session.flush()
    return answer


def _find_answer(session: Any, intent_key: str, source_type: str) -> IntentAnswer | None:
    return session.scalar(
        select(IntentAnswer).where(
            IntentAnswer.intent_key == intent_key,
            IntentAnswer.source_type == source_type,
            IntentAnswer.is_active.is_(True),
        )
    )


def _select_seeded_answer(session: Any, message: str) -> dict[str, Any]:
    normalized = message.strip()
    if "三里屯" in normalized and "川菜" in normalized:
        answer = _find_answer(session, AREA_INTENT_KEY, "area_intent_answer")
        return {
            "answer": answer,
            "intent_key": AREA_INTENT_KEY,
            "source_answer_type": "area_intent_answer" if answer else None,
            "location_state": "in_area",
            "confidence": answer.confidence if answer and answer.confidence is not None else 0.0,
        }
    if "四季民福" in normalized and any(word in normalized for word in ["点菜", "吃什么", "哪个菜", "第一次"]):
        answer = _find_answer(session, VENUE_INTENT_KEY, "ordering_bundle_answer")
        return {
            "answer": answer,
            "intent_key": VENUE_INTENT_KEY,
            "source_answer_type": "ordering_bundle_answer" if answer else None,
            "location_state": "in_venue",
            "confidence": answer.confidence if answer and answer.confidence is not None else 0.0,
        }
    if any(word in normalized for word in ["店", "餐厅", "到店", "菜单", "点菜"]):
        location_state: Literal["in_area", "in_venue", "unknown"] = "in_venue"
    elif any(word in normalized for word in ["附近", "区域", "商圈", "哪儿", "哪里"]):
        location_state = "in_area"
    else:
        location_state = "unknown"
    return {
        "answer": None,
        "intent_key": "eval.food_beijing_onsite_v1.unknown",
        "source_answer_type": None,
        "location_state": location_state,
        "confidence": 0.0,
    }


def _create_eval_retrieval_run(
    session: Any,
    *,
    agent_run: AgentRun,
    turn: Turn,
    message: str,
    source_answer: IntentAnswer | None,
    source_answer_type: str | None,
    confidence: float,
) -> RetrievalRun:
    run = RetrievalRun(
        agent_run_id=agent_run.id,
        turn_id=turn.id,
        query=message,
        source="eval_seed",
        status="succeeded",
        top_k=8,
        filters_json={"namespace": EVAL_NAMESPACE, "pack_id": PACK_ID},
        metadata_json={"namespace": EVAL_NAMESPACE},
        finished_at=utcnow(),
    )
    session.add(run)
    session.flush()
    if source_answer is not None:
        hit = RetrievalHit(
            retrieval_run_id=run.id,
            rank=1,
            score=confidence,
            source_type=source_answer_type or "intent_answer",
            source_id=str(source_answer.id),
            title=source_answer.answer_title,
            snippet=source_answer.answer_summary,
            payload_json={
                "namespace": EVAL_NAMESPACE,
                "pack_id": PACK_ID,
                "source_answer_type": source_answer_type,
                "target_type": (source_answer.constraints_json or {}).get("target_type"),
                "intent_key": source_answer.intent_key,
            },
        )
        session.add(hit)
        session.flush()
    return run


def _create_eval_recommendation(
    session: Any,
    *,
    user: User,
    conversation: Conversation,
    question: Question,
    user_turn: Turn,
    agent_run: AgentRun,
    retrieval_run: RetrievalRun,
    answer: IntentAnswer,
    source_answer_type: str,
    location_state: str,
) -> dict[str, Any]:
    payload = answer.evidence_json or {}
    target_type = (answer.constraints_json or {}).get("target_type", "restaurant")
    decision_factor = payload.get("decision_factor") or {"text": answer.answer_summary}
    tool_call = create_tool_call(
        session,
        agent_run=agent_run,
        turn=user_turn,
        name="create_recommendation_card",
        arguments={
            "item": {"title": answer.answer_title, "subtitle": answer.answer_summary, "category": target_type},
            "decision_factor": decision_factor,
            "image_asset_id": None,
            "evidence_ids": [str(hit.id) for hit in retrieval_run.hits],
            "retrieval_run_id": str(retrieval_run.id),
        },
    )
    card = RecommendationCard(
        question_id=question.id,
        conversation_id=conversation.id,
        user_id=user.id,
        agent_run_id=agent_run.id,
        tool_call_id=tool_call.id,
        image_asset_id=None,
        image_required=False,
        image_status="missing",
        source="eval_seed",
        title=answer.answer_title or "就选这个",
        subtitle=answer.answer_summary,
        reason=str(decision_factor.get("text") or answer.answer_summary),
        bullets_json=[],
        warning=None,
        confidence=answer.confidence,
        status="ready",
        payload_json={
            "namespace": EVAL_NAMESPACE,
            "pack_id": PACK_ID,
            "version": CARD_VERSION,
            "target_type": target_type,
            "item": {"title": answer.answer_title, "subtitle": answer.answer_summary, "category": target_type},
            "decision_factor": decision_factor,
            "provenance": {
                "source": "eval_seed",
                "source_answer_type": source_answer_type,
                "intent_answer_id": str(answer.id),
                "retrieval_run_id": str(retrieval_run.id),
            },
            "ui": payload.get("ui", {"density": "single_card"}),
            "location_state": location_state,
        },
    )
    session.add(card)
    session.flush()
    question.current_recommendation_card_id = card.id
    question.status = "top1_ready"
    finish_tool_call(
        tool_call,
        status="succeeded",
        result={"ui_event": "show_recommendation_card", "card_id": str(card.id)},
    )
    card_view = serialize_eval_card(card)
    ui_events = [
        {
            "type": "show_recommendation_card",
            "card_id": str(card.id),
            "recommendation_card": card_view,
        }
    ]
    return {
        "data": {"recommendation_card": card_view},
        "ui_events": ui_events,
        "cards": [card_view],
        "help_cards": [],
        "tool_calls": [_serialize_tool_call(tool_call)],
        "tool_call_ids": [str(tool_call.id)],
        "debug_base": {
            "card_id": str(card.id),
            "retrieval_hit_ids": [str(hit.id) for hit in retrieval_run.hits],
        },
    }


def _create_eval_help_card(
    session: Any,
    *,
    user: User,
    conversation: Conversation,
    question: Question,
    user_turn: Turn,
    agent_run: AgentRun,
    location_state: str,
) -> dict[str, Any]:
    title = question.raw_text.strip() or "求一个"
    context = {"raw_text": question.raw_text, "source": "pipi-eval-lab"}
    wants = ["一个能直接照着选的建议"]
    avoids = ["不稳定证据", "硬推榜单"]
    constraints = ["只要一个选择", "证据不足先求助"]
    tool_call = create_tool_call(
        session,
        agent_run=agent_run,
        turn=user_turn,
        name="draft_help_card",
        arguments={
            "title": title,
            "context": context,
            "wants": wants,
            "avoids": avoids,
            "constraints": constraints,
        },
    )
    help_card = HelpCard(
        question_id=question.id,
        conversation_id=conversation.id,
        owner_user_id=user.id,
        title=title,
        prompt=title,
        context_text="证据不足，先求懂的人来一句。",
        status="draft",
        answer_count=0,
        min_answers_required=3,
        payload_json={
            "namespace": EVAL_NAMESPACE,
            "pack_id": PACK_ID,
            "version": CARD_VERSION,
            "location_state": location_state,
            "context": context,
            "wants": wants,
            "avoids": avoids,
            "constraints": constraints,
            "reward": {"label": "+10", "value": 10},
            "answer_stats": {"count": 0, "min_required": 3},
            "revision": 1,
        },
    )
    session.add(help_card)
    session.flush()
    question.current_help_card_id = help_card.id
    question.status = "help_draft"
    finish_tool_call(
        tool_call,
        status="succeeded",
        result={"ui_event": "show_help_card_draft", "help_card_id": str(help_card.id)},
    )
    help_view = serialize_eval_help_card(help_card)
    ui_events = [
        {
            "type": "show_help_card_draft",
            "help_card_id": str(help_card.id),
            "help_card": help_view,
        }
    ]
    return {
        "data": {"help_card": help_view},
        "ui_events": ui_events,
        "cards": [],
        "help_cards": [help_view],
        "tool_calls": [_serialize_tool_call(tool_call)],
        "tool_call_ids": [str(tool_call.id)],
        "debug_base": {"help_card_id": str(help_card.id)},
    }


def _serialize_turn(turn: Turn) -> dict[str, Any]:
    return {
        "id": str(turn.id),
        "conversation_id": str(turn.conversation_id),
        "role": turn.role,
        "content": turn.content,
        "turn_index": turn.turn_index,
        "status": turn.status,
        "content_json": turn.content_json,
        "created_at": _iso(turn.created_at),
    }


def _serialize_agent_run(run: AgentRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "turn_id": str(run.turn_id) if run.turn_id else None,
        "run_type": run.run_type,
        "graph_name": run.graph_name,
        "model_provider": run.model_provider,
        "model_name": run.model_name,
        "status": run.status,
        "input_json": run.input_json,
        "output_json": run.output_json,
        "metadata_json": run.metadata_json,
        "error_message": run.error_message,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def _serialize_tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "agent_run_id": str(call.agent_run_id),
        "turn_id": str(call.turn_id) if call.turn_id else None,
        "name": call.tool_name,
        "tool_name": call.tool_name,
        "status": call.status,
        "sequence_index": call.sequence_index,
        "arguments": call.arguments_json,
        "result": call.result_json,
        "error": call.error_message,
        "created_at": _iso(call.created_at),
        "started_at": _iso(call.started_at),
        "finished_at": _iso(call.finished_at),
    }


def _serialize_retrieval_run(run: RetrievalRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "agent_run_id": str(run.agent_run_id),
        "turn_id": str(run.turn_id) if run.turn_id else None,
        "query": run.query,
        "source": run.source,
        "status": run.status,
        "top_k": run.top_k,
        "filters_json": run.filters_json,
        "metadata_json": run.metadata_json,
        "hits": [_serialize_retrieval_hit(hit) for hit in run.hits],
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def _serialize_retrieval_hit(hit: RetrievalHit) -> dict[str, Any]:
    return {
        "id": str(hit.id),
        "retrieval_run_id": str(hit.retrieval_run_id),
        "rank": hit.rank,
        "score": hit.score,
        "source_type": hit.source_type,
        "source_id": hit.source_id,
        "source_uri": hit.source_uri,
        "title": hit.title,
        "snippet": hit.snippet,
        "payload_json": hit.payload_json,
        "created_at": _iso(hit.created_at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
