from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.jobs.finalizer_job import run_finalize_graph_for_help_card
from app.models import HelpAnswer, HelpCard, RewardEvent
from app.services.help_service import assess_one_liner_quality, normalize_one_liner_key, one_liner_quality_metadata
from app.services.runtime import (
    ensure_user,
    resolve_request_user,
    serialize_help_card,
    session_scope,
    utcnow,
)
from app.services.user_events import record_user_behavior_event


def list_help_feed(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    limit: int = 10,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_limit = max(1, min(int(limit or 10), 100))
    try:
        offset = max(0, int(cursor or 0))
    except ValueError:
        offset = 0

    with session_scope() as session:
        user = resolve_request_user(session, user_id=user_id, device_uid=device_uid)
        answered_ids: set[uuid.UUID] = set()
        if user is not None:
            answered_ids = set(
                session.scalars(select(HelpAnswer.help_card_id).where(HelpAnswer.answer_user_id == user.id))
            )
        query = (
            select(HelpCard)
            .where(HelpCard.status.in_(["published", "collecting"]))
            .order_by(HelpCard.published_at.desc().nullslast(), HelpCard.created_at.desc())
            .limit(max(500, offset + resolved_limit + 1))
        )
        if user is not None:
            query = query.where(HelpCard.owner_user_id != user.id)
        if answered_ids:
            query = query.where(~HelpCard.id.in_(answered_ids))
        rows = sorted(session.scalars(query), key=help_feed_sort_key)
        items = rows[offset : offset + resolved_limit]
        next_cursor = str(offset + resolved_limit) if len(rows) > offset + resolved_limit else None
        return {"items": [_serialize_ranked_help_card(card) for card in items], "next_cursor": next_cursor}


def get_help_card(id: str) -> dict[str, Any]:
    from app.services.smoke_runtime import get_smoke_help_card

    smoke_help_card = get_smoke_help_card(id)
    if smoke_help_card is not None:
        return smoke_help_card

    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(id))
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        help_card_detail = serialize_help_card(help_card)
        return {"help_card": help_card_detail, **help_card_detail}


def publish_help_card(id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(id))
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        publish_user = ensure_user(
            session,
            device_uid=payload.get("device_uid") or payload.get("device_id") or payload.get("user_id"),
            user_id=payload.get("user_id"),
        )
        if help_card.status not in {"draft", "published", "collecting"}:
            raise HTTPException(status_code=409, detail="help_card_not_publishable")
        if help_card.status == "draft":
            help_card.status = "published"
            help_card.published_at = help_card.published_at or utcnow()
        record_user_behavior_event(
            session,
            event_type="help_card_published",
            user_id=publish_user.id,
            conversation_id=help_card.conversation_id,
            help_card_id=help_card.id,
            source="api",
            payload_json={"status": help_card.status, **dict(payload.get("metadata") or {})},
        )
        session.flush()
        return {
            "help_card": {"id": str(help_card.id), "status": help_card.status},
            "ui_events": [{"type": "help_card_published", "help_card_id": str(help_card.id)}],
        }


def create_one_liner(id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(id))
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        raw_text = str(payload.get("text") or "")
        text = raw_text.strip()
        if len(text) < 2:
            raise HTTPException(status_code=422, detail="one_liner_too_short")
        if len(text) > 240:
            raise HTTPException(status_code=422, detail="one_liner_too_long")
        quality = assess_one_liner_quality(text)
        if not quality.accepted:
            raise HTTPException(
                status_code=422,
                detail={"code": "one_liner_low_quality", "reason": quality.reason},
            )
        answer_user = ensure_user(
            session,
            device_uid=payload.get("device_uid") or payload.get("device_id") or payload.get("user_id"),
            user_id=payload.get("user_id"),
        )
        if answer_user.id == help_card.owner_user_id:
            raise HTTPException(status_code=403, detail="owner_cannot_answer_own_help_card")
        if help_card.status not in {"published", "collecting"}:
            raise HTTPException(status_code=409, detail="help_card_not_collecting")
        existing = session.scalar(
            select(HelpAnswer).where(
                HelpAnswer.help_card_id == help_card.id,
                HelpAnswer.answer_user_id == answer_user.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="already_answered")
        sibling_answers = session.scalars(
            select(HelpAnswer).where(HelpAnswer.help_card_id == help_card.id)
        )
        for sibling in sibling_answers:
            sibling_key = str((sibling.evidence_json or {}).get("normalized_key") or "")
            sibling_key = sibling_key or normalize_one_liner_key(sibling.normalized_text or sibling.raw_text)
            if sibling_key and sibling_key == quality.normalized_key:
                raise HTTPException(status_code=409, detail="duplicate_answer")

        reward = _reward_payload(help_card)
        answer = HelpAnswer(
            help_card_id=help_card.id,
            answer_user_id=answer_user.id,
            raw_text=text,
            normalized_text=text,
            status="submitted",
            reward_status="pending",
            evidence_json={
                "evidence_type": "human_one_liner",
                "reward": reward,
                "quality": one_liner_quality_metadata(quality),
                "normalized_key": quality.normalized_key,
            },
        )
        session.add(answer)
        session.flush()
        session.add(
            RewardEvent(
                user_id=answer_user.id,
                help_card_id=help_card.id,
                help_answer_id=answer.id,
                event_type="one_liner_submitted",
                label=str(reward["label"]),
                value=int(reward["value"]),
                status="pending",
                payload_json={"help_card_title": help_card.title},
            )
        )
        record_user_behavior_event(
            session,
            event_type="one_liner_submitted",
            user_id=answer_user.id,
            conversation_id=help_card.conversation_id,
            help_card_id=help_card.id,
            help_answer_id=answer.id,
            source="api",
            payload_json={"reward": reward, **dict(payload.get("metadata") or {})},
        )
        help_card.answer_count += 1
        help_card.status = "collecting"
        if help_card.question is not None:
            help_card.question.status = "collecting_answers"
        session.flush()

        finalization_ready = help_card.answer_count >= help_card.min_answers_required
        final_card_id: str | None = None
        if finalization_ready:
            final_state = run_finalize_graph_for_help_card(session, help_card.id)
            final_card = final_state.get("final_recommendation_card") or {}
            final_card_id = str(final_card.get("id") or final_card.get("card_id") or "") or None

        return {
            "help_card_id": str(help_card.id),
            "answer_id": str(answer.id),
            "accepted": True,
            "answer": {
                "id": str(answer.id),
                "help_card_id": str(help_card.id),
                "raw_text": answer.raw_text,
                "status": answer.status,
                "reward_status": answer.reward_status,
            },
            "help_card": {
                "id": str(help_card.id),
                "answer_count": help_card.answer_count,
                "status": help_card.status,
            },
            "reward": reward,
            "should_advance": True,
            "toast": f"收到了，{reward['label']} 等她采纳。",
            "metadata": {
                "evidence_type": "human_one_liner",
                "answer_count": help_card.answer_count,
                "finalization_ready": finalization_ready,
                "final_card_id": final_card_id,
            },
        }


def get_my_rewards(*, user_id: str | None = None, device_uid: str | None = None) -> dict[str, Any]:
    with session_scope() as session:
        user = ensure_user(session, device_uid=device_uid or user_id, user_id=user_id)
        rows = list(
            session.scalars(
                select(RewardEvent)
                .where(RewardEvent.user_id == user.id)
                .order_by(RewardEvent.created_at.desc())
                .limit(100)
            )
        )
        pending_value = sum(event.value for event in rows if event.status == "pending")
        granted_value = sum(event.value for event in rows if event.status == "granted")
        rejected_value = sum(event.value for event in rows if event.status == "rejected")
        return {
            "device_uid": user.device_uid,
            "pending_value": pending_value,
            "granted_value": granted_value,
            "rejected_value": rejected_value,
            "items": [
                {
                    "id": str(event.id),
                    "type": event.event_type,
                    "label": event.label,
                    "value": event.value,
                    "status": event.status,
                    "help_card_id": str(event.help_card_id) if event.help_card_id else None,
                    "help_answer_id": str(event.help_answer_id) if event.help_answer_id else None,
                    "created_at": event.created_at,
                }
                for event in rows
            ],
        }


def _reward_payload(help_card: HelpCard) -> dict[str, Any]:
    payload = help_card.payload_json or {}
    reward = dict(payload.get("reward") or {})
    value = int(reward.get("value") or payload.get("reward_value") or 10)
    return {
        "label": str(reward.get("label") or f"+{value}"),
        "value": value,
        "status": str(reward.get("status") or "pending"),
    }


def _serialize_ranked_help_card(help_card: HelpCard) -> dict[str, Any]:
    item = serialize_help_card(help_card)
    metadata = dict(item.get("metadata") or {})
    metadata["feed_ranking"] = help_feed_rank_payload(help_card)
    item["metadata"] = metadata
    return item


def help_feed_rank_payload(help_card: HelpCard) -> dict[str, Any]:
    answer_count = int(getattr(help_card, "answer_count", 0) or 0)
    min_required = int(getattr(help_card, "min_answers_required", 3) or 3)
    reward_value = _help_card_reward_value(help_card)
    remaining_answers = max(0, min_required - answer_count)
    return {
        "reward_value": reward_value,
        "answer_count": answer_count,
        "min_answers_required": min_required,
        "remaining_answers": remaining_answers,
        "score": _help_feed_score(
            reward_value=reward_value,
            remaining_answers=remaining_answers,
            answer_count=answer_count,
        ),
    }


def help_feed_sort_key(help_card: HelpCard) -> tuple[float, int, int, float, float]:
    rank = help_feed_rank_payload(help_card)
    published_ts = _timestamp(getattr(help_card, "published_at", None))
    created_ts = _timestamp(getattr(help_card, "created_at", None))
    return (
        -float(rank["score"]),
        -int(rank["reward_value"]),
        int(rank["answer_count"]),
        -published_ts,
        -created_ts,
    )


def _help_feed_score(*, reward_value: int, remaining_answers: int, answer_count: int) -> float:
    return float(reward_value * 100 + remaining_answers * 20 - answer_count * 5)


def _help_card_reward_value(help_card: HelpCard) -> int:
    payload = getattr(help_card, "payload_json", None) or {}
    reward = dict(payload.get("reward") or {})
    return int(reward.get("value") or payload.get("reward_value") or 10)


def _timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return 0.0


__all__ = [
    "create_one_liner",
    "get_help_card",
    "get_my_rewards",
    "help_feed_rank_payload",
    "help_feed_sort_key",
    "list_help_feed",
    "publish_help_card",
]
