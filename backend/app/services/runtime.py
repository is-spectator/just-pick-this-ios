from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import make_session_factory
from app.models import (
    AgentRun,
    Conversation,
    HelpCard,
    ImageAsset,
    Intent,
    IntentAnswer,
    LightEvent,
    Question,
    RecommendationCard,
    RetrievalRun,
    ToolCall,
    Turn,
    User,
)
from app.services.seed_service import (
    DATONG_IMAGE_ASSET_ID,
    FOOD_INTENT_ID,
    FOOD_INTENT_ANSWER_ID,
    SIJIMINFU_IMAGE_ASSET_ID,
    SIJIMINFU_INTENT_ANSWER_ID,
    SEONGSU_IMAGE_ASSET_ID,
    SHOPPING_INTENT_ANSWER_ID,
    SHOPPING_INTENT_ID,
    seed_initial_data,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    session_factory = make_session_factory()
    with session_factory() as session:
        if get_settings().auto_seed_on_request:
            ensure_seed_data(session)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def ensure_seed_data(session: Session) -> None:
    datong_image = session.get(ImageAsset, DATONG_IMAGE_ASSET_ID)
    seongsu_image = session.get(ImageAsset, SEONGSU_IMAGE_ASSET_ID)
    sijiminfu_image = session.get(ImageAsset, SIJIMINFU_IMAGE_ASSET_ID)
    seed_required = (
        datong_image is None
        or seongsu_image is None
        or sijiminfu_image is None
        or datong_image.source_domain is None
        or seongsu_image.source_domain is None
        or sijiminfu_image.source_domain is None
        or session.get(Intent, FOOD_INTENT_ID) is None
        or session.get(Intent, SHOPPING_INTENT_ID) is None
        or session.get(IntentAnswer, FOOD_INTENT_ANSWER_ID) is None
        or session.get(IntentAnswer, SHOPPING_INTENT_ANSWER_ID) is None
        or session.get(IntentAnswer, SIJIMINFU_INTENT_ANSWER_ID) is None
    )
    if seed_required:
        seed_initial_data(session)


def normalize_external_user_id(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def ensure_user(
    session: Session,
    *,
    device_uid: str | None = None,
    user_id: str | None = None,
    platform: str | None = None,
    app_version: str | None = None,
) -> User:
    settings = get_settings()
    external_uid = normalize_external_user_id(device_uid)
    user: User | None = None
    if external_uid is None and user_id:
        user = _user_by_external_or_uuid(session, user_id)
        if user is None and not settings.require_device_uid:
            external_uid = normalize_external_user_id(user_id)
    if external_uid is None and user is None:
        if settings.require_device_uid:
            raise ValueError("device_uid is required")
        external_uid = f"anonymous-{uuid.uuid4()}"

    if user is None:
        user = session.scalar(select(User).where(User.device_uid == external_uid))
    if user is None:
        user = User(
            device_uid=external_uid,
            display_name="路过的人",
            platform=platform,
            app_version=app_version,
            last_seen_at=utcnow(),
        )
        session.add(user)
        session.flush()
    else:
        user.platform = platform or user.platform
        user.app_version = app_version or user.app_version
        user.last_seen_at = utcnow()
    return user


def resolve_request_user(
    session: Session,
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
) -> User | None:
    external_uid = normalize_external_user_id(device_uid) or normalize_external_user_id(user_id)
    if external_uid is None:
        return None
    user = _user_by_external_or_uuid(session, external_uid)
    if user is not None:
        return user
    return ensure_user(session, device_uid=external_uid)


def get_or_create_conversation(
    session: Session,
    *,
    user: User,
    conversation_id: str | None = None,
    always_create: bool = False,
) -> Conversation:
    if conversation_id:
        conversation = session.get(Conversation, uuid.UUID(conversation_id))
        if conversation is None:
            raise ValueError("conversation not found")
        return conversation

    if not always_create:
        conversation = session.scalar(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.status == "active")
            .order_by(Conversation.created_at.desc())
        )
        if conversation is not None:
            return conversation

    conversation = Conversation(user_id=user.id, status="active")
    session.add(conversation)
    session.flush()
    return conversation


def create_turn(
    session: Session,
    *,
    conversation: Conversation,
    user: User | None,
    role: str,
    content: str,
    content_json: dict[str, Any] | None = None,
) -> Turn:
    next_index = (
        session.scalar(
            select(func.coalesce(func.max(Turn.turn_index), 0)).where(
                Turn.conversation_id == conversation.id
            )
        )
        or 0
    ) + 1
    turn = Turn(
        conversation_id=conversation.id,
        user_id=user.id if user is not None else None,
        role=role,
        content=content,
        content_json=content_json or {},
        turn_index=next_index,
    )
    session.add(turn)
    session.flush()
    return turn


def create_question_for_turn(session: Session, *, conversation: Conversation, user: User, turn: Turn) -> Question:
    question = Question(
        conversation_id=conversation.id,
        turn_id=turn.id,
        user_id=user.id,
        raw_text=turn.content,
        normalized_text=turn.content.strip(),
        status="received",
    )
    session.add(question)
    session.flush()
    return question


def latest_active_help_card(session: Session, *, conversation_id: uuid.UUID) -> HelpCard | None:
    return session.scalar(
        select(HelpCard)
        .where(
            HelpCard.conversation_id == conversation_id,
            HelpCard.status.in_(["draft", "published", "collecting", "final_ready"]),
        )
        .order_by(HelpCard.created_at.desc())
    )


def latest_question(session: Session, *, conversation_id: uuid.UUID) -> Question | None:
    return session.scalar(
        select(Question)
        .where(Question.conversation_id == conversation_id)
        .order_by(Question.created_at.desc())
    )


def serialize_image(image: ImageAsset | None) -> dict[str, Any] | None:
    if image is None:
        return None
    return {
        "id": str(image.id),
        "url": image.url,
        "source_url": image.source_url,
        "source_domain": image.source_domain,
        "caption": "参考图片",
        "alt_text": image.alt_text,
        "verified": image.verified and image.verification_status == "verified" and image.displayable,
        "displayable": image.displayable,
        "verification_status": image.verification_status,
        "is_ai_generated": image.is_ai_generated,
        "source_type": image.source_type,
        "license_note": image.license_note,
        "metadata": {
            "place_key": image.place_key,
            "item_key": image.item_key,
            "credit": image.credit,
            "ai_generated_risk": image.ai_generated_risk,
        },
    }


def serialize_card(card: RecommendationCard) -> dict[str, Any]:
    payload = card.payload_json or {}
    return {
        "id": str(card.id),
        "type": "recommendation_card",
        "version": payload.get("version"),
        "target_type": payload.get("target_type"),
        "location_state": payload.get("location_state"),
        "title": card.title,
        "subtitle": card.subtitle,
        "one_liner": card.reason,
        "status": card.status,
        "image": serialize_image(card.image_asset),
        "place": payload.get("place"),
        "route": payload.get("route"),
        "action": payload.get("action"),
        "image_status": card.image_status,
        "image_required": card.image_required,
        "item": payload.get("item", {"title": card.title}),
        "decision_factor": payload.get("decision_factor", {"text": card.reason}),
        "provenance": payload.get("provenance", {}),
        "ui": payload.get("ui", {}),
        "metadata": {
            "question_id": str(card.question_id),
            "confidence": card.confidence,
            "source": card.source,
            "composer": _public_composer_metadata(payload.get("composer")),
        },
    }


def _public_composer_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = {
        "provider",
        "model",
        "used_web_search",
        "composition",
        "reference_answer_id",
        "composer_fallback",
    }
    return {key: value[key] for key in allowed if key in value}


def serialize_card_detail(card: RecommendationCard) -> dict[str, Any]:
    data = serialize_card(card)
    raw_evidence = card.payload_json.get("evidence_ids", [])
    evidence = [
        item if isinstance(item, dict) else {"id": str(item), "type": "retrieval_hit"}
        for item in raw_evidence
    ]
    data.update(
        {
            "description": card.reason,
            "evidence": evidence,
            "created_at": card.created_at,
            "updated_at": card.updated_at,
        }
    )
    return data


def serialize_help_card(help_card: HelpCard) -> dict[str, Any]:
    payload = help_card.payload_json or {}
    answer_stats = dict(payload.get("answer_stats") or {})
    answer_stats["count"] = help_card.answer_count
    answer_stats["min_required"] = help_card.min_answers_required
    reward = dict(payload.get("reward") or {})
    reward_value = int(reward.get("value") or payload.get("reward_value") or 10)
    reward.setdefault("value", reward_value)
    reward.setdefault("label", f"+{reward_value}")
    reward.setdefault("status", "pending")
    return {
        "id": str(help_card.id),
        "type": "help_card",
        "version": payload.get("version"),
        "title": help_card.title,
        "prompt": help_card.prompt,
        "location_state": payload.get("location_state"),
        "context": payload.get("context", {}),
        "wants": payload.get("wants", []),
        "avoids": payload.get("avoids", []),
        "constraints": payload.get("constraints", []),
        "reward": reward,
        "answer_stats": answer_stats,
        "revision": payload.get("revision"),
        "status": help_card.status,
        "context_text": help_card.context_text,
        "answer_count": help_card.answer_count,
        "one_liner": help_card.context_text,
        "card": serialize_card(help_card.final_recommendation_card)
        if help_card.final_recommendation_card is not None
        else None,
        "metadata": {
            "question_id": str(help_card.question_id),
            "answer_count": help_card.answer_count,
            "min_answers_required": help_card.min_answers_required,
            "owner_user_id": str(help_card.owner_user_id),
        },
        "created_at": help_card.created_at,
    }


def serialize_light_event(event: LightEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "kind": event.type,
        "type": event.type,
        "title": event.title,
        "message": event.body,
        "body": event.body,
        "card_id": str(event.recommendation_card_id) if event.recommendation_card_id else None,
        "help_card_id": str(event.help_card_id) if event.help_card_id else None,
        "lit_at": event.lit_at,
        "created_at": event.created_at,
        "metadata": event.payload_json,
    }


def serialize_tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "name": call.tool_name,
        "status": "succeeded" if call.status == "succeeded" else call.status,
        "arguments": call.arguments_json,
        "result": call.result_json or {},
        "error": call.error_message,
    }


def serialize_retrieval(run: RetrievalRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "status": "succeeded" if run.status == "succeeded" else run.status,
        "query": run.query,
        "metadata": run.metadata_json or {},
        "hits": [
            {
                "id": str(hit.id),
                "score": hit.score,
                "source_id": hit.source_id,
                "image_asset_id": hit.payload_json.get("image_asset_id"),
                "evidence_id": str(hit.id),
                "title": hit.title,
            }
            for hit in run.hits
        ],
    }


def build_card_ui_event(card: RecommendationCard) -> dict[str, Any]:
    return {"type": "show_recommendation_card", "card_id": str(card.id), "card": serialize_card(card)}


def build_help_ui_event(help_card: HelpCard, event_type: str = "show_help_card_draft") -> dict[str, Any]:
    return {"type": event_type, "help_card_id": str(help_card.id), "help_card": serialize_help_card(help_card)}


def create_tool_call(
    session: Session,
    *,
    agent_run: AgentRun,
    turn: Turn | None,
    name: str,
    arguments: dict[str, Any],
    sequence_index: int = 0,
) -> ToolCall:
    tool_call = ToolCall(
        agent_run_id=agent_run.id,
        turn_id=turn.id if turn else None,
        tool_name=name,
        arguments_json=arguments,
        status="running",
        sequence_index=sequence_index,
    )
    session.add(tool_call)
    session.flush()
    return tool_call


def finish_tool_call(
    tool_call: ToolCall,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    tool_call.status = status
    tool_call.result_json = result
    tool_call.error_message = error
    tool_call.finished_at = utcnow()


def ensure_datong_assets(session: Session) -> tuple[ImageAsset, IntentAnswer]:
    image = session.get(ImageAsset, DATONG_IMAGE_ASSET_ID)
    answer = session.get(IntentAnswer, FOOD_INTENT_ANSWER_ID)
    if image is None or answer is None:
        seed_initial_data(session)
        image = session.get(ImageAsset, DATONG_IMAGE_ASSET_ID)
        answer = session.get(IntentAnswer, FOOD_INTENT_ANSWER_ID)
    if image is None or answer is None:
        raise RuntimeError("seeded Datong image asset or intent answer missing")
    return image, answer


def ensure_seongsu_image(session: Session) -> ImageAsset:
    image = session.get(ImageAsset, SEONGSU_IMAGE_ASSET_ID)
    if image is None:
        seed_initial_data(session)
        image = session.get(ImageAsset, SEONGSU_IMAGE_ASSET_ID)
    if image is None:
        raise RuntimeError("seeded Seongsu image asset missing")
    return image


def ensure_seongsu_assets(session: Session) -> tuple[ImageAsset, IntentAnswer]:
    image = session.get(ImageAsset, SEONGSU_IMAGE_ASSET_ID)
    answer = session.get(IntentAnswer, SHOPPING_INTENT_ANSWER_ID)
    if image is None or answer is None:
        seed_initial_data(session)
        image = session.get(ImageAsset, SEONGSU_IMAGE_ASSET_ID)
        answer = session.get(IntentAnswer, SHOPPING_INTENT_ANSWER_ID)
    if image is None or answer is None:
        raise RuntimeError("seeded Seongsu image asset or intent answer missing")
    return image, answer


def ensure_sijiminfu_assets(session: Session) -> tuple[ImageAsset, IntentAnswer]:
    image = session.get(ImageAsset, SIJIMINFU_IMAGE_ASSET_ID)
    answer = session.get(IntentAnswer, SIJIMINFU_INTENT_ANSWER_ID)
    if image is None or answer is None:
        seed_initial_data(session)
        image = session.get(ImageAsset, SIJIMINFU_IMAGE_ASSET_ID)
        answer = session.get(IntentAnswer, SIJIMINFU_INTENT_ANSWER_ID)
    if image is None or answer is None:
        raise RuntimeError("seeded Siji Minfu image asset or intent answer missing")
    return image, answer


def ensure_shopping_intent(session: Session) -> Intent:
    intent = session.get(Intent, SHOPPING_INTENT_ID)
    if intent is None:
        seed_initial_data(session)
        intent = session.get(Intent, SHOPPING_INTENT_ID)
    if intent is None:
        raise RuntimeError("seeded shopping intent missing")
    return intent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_by_external_or_uuid(session: Session, value: str) -> User | None:
    try:
        user_id = uuid.UUID(value)
    except ValueError:
        user_id = None
    if user_id is not None:
        user = session.get(User, user_id)
        if user is not None:
            return user
    return session.scalar(select(User).where(User.device_uid == value))
