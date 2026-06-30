from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.finalizer_job import run_finalize_graph_for_help_card
from app.models import ContentReviewTask, HelpAnswer, HelpCard, RewardEvent, UserBehaviorEvent
from app.services.help_service import (
    HelpCardAbuseCheck,
    OneLinerAbuseCheck,
    OneLinerQuality,
    assess_one_liner_quality,
    detect_help_card_abuse,
    detect_one_liner_abuse,
    normalize_one_liner_key,
    one_liner_quality_metadata,
)
from app.services.runtime import (
    ensure_user,
    resolve_request_user,
    serialize_help_card,
    session_scope,
    utcnow,
)
from app.services.user_preferences import PREFERENCE_PROFILE_KEY
from app.services.user_events import record_user_behavior_event
from app.services.user_events import serialize_user_behavior_event


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
        skipped_ids: set[uuid.UUID] = set()
        if user is not None:
            skipped_ids = set(
                session.scalars(
                    select(UserBehaviorEvent.help_card_id).where(
                        UserBehaviorEvent.user_id == user.id,
                        UserBehaviorEvent.event_type == "help_card_skipped",
                        UserBehaviorEvent.help_card_id.is_not(None),
                    )
                )
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
        if skipped_ids:
            query = query.where(~HelpCard.id.in_(skipped_ids))
        answerer_preferences = _answerer_preference_summary(user)
        rows = [card for card in session.scalars(query) if not _help_card_abuse(card).unsafe]
        rows = sorted(rows, key=lambda card: help_feed_sort_key(card, answerer_preferences=answerer_preferences))
        items = rows[offset : offset + resolved_limit]
        if user is not None and items:
            shown_ids = [str(card.id) for card in items]
            for rank_index, card in enumerate(items):
                record_user_behavior_event(
                    session,
                    event_type="help_feed_impression",
                    user_id=user.id,
                    conversation_id=card.conversation_id,
                    help_card_id=card.id,
                    source="help_feed",
                    payload_json={
                        "rank_index": offset + rank_index,
                        "page_index": rank_index,
                        "limit": resolved_limit,
                        "cursor": cursor,
                        "shown_help_card_ids": shown_ids,
                        "feed_ranking": help_feed_rank_payload(
                            card,
                            answerer_preferences=answerer_preferences,
                        ),
                    },
                )
            session.flush()
        next_cursor = str(offset + resolved_limit) if len(rows) > offset + resolved_limit else None
        return {
            "items": [
                _serialize_ranked_help_card(card, answerer_preferences=answerer_preferences)
                for card in items
            ],
            "next_cursor": next_cursor,
        }


def list_my_help_cards(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_limit = max(1, min(int(limit or 50), 100))
    try:
        offset = max(0, int(cursor or 0))
    except ValueError:
        offset = 0

    with session_scope() as session:
        user = ensure_user(session, user_id=user_id, device_uid=device_uid)
        rows = list(
            session.scalars(
                select(HelpCard)
                .where(HelpCard.owner_user_id == user.id)
                .order_by(HelpCard.created_at.desc())
                .offset(offset)
                .limit(resolved_limit + 1)
            )
        )
        items = rows[:resolved_limit]
        next_cursor = str(offset + resolved_limit) if len(rows) > resolved_limit else None
        return {
            "items": [serialize_help_card(card) for card in items],
            "next_cursor": next_cursor,
        }


def list_my_help_answers(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_limit = max(1, min(int(limit or 50), 100))
    try:
        offset = max(0, int(cursor or 0))
    except ValueError:
        offset = 0

    with session_scope() as session:
        user = ensure_user(session, user_id=user_id, device_uid=device_uid)
        rows = list(
            session.scalars(
                select(HelpAnswer)
                .where(HelpAnswer.answer_user_id == user.id)
                .order_by(HelpAnswer.created_at.desc())
                .offset(offset)
                .limit(resolved_limit + 1)
            )
        )
        items = rows[:resolved_limit]
        next_cursor = str(offset + resolved_limit) if len(rows) > resolved_limit else None
        return {
            "items": [_serialize_help_answer(answer) for answer in items],
            "next_cursor": next_cursor,
        }


def help_feed_conversion_summary(
    session: Session,
    *,
    since_hours: int = 24 * 7,
    target_uplift: float = 0.2,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    events = session.scalars(
        select(UserBehaviorEvent)
        .where(
            UserBehaviorEvent.event_type.in_(
                ["help_feed_impression", "one_liner_submitted", "help_card_skipped"]
            ),
            UserBehaviorEvent.created_at >= start,
        )
        .order_by(UserBehaviorEvent.created_at.asc())
    ).all()
    return help_feed_conversion_summary_from_events(
        events,
        target_uplift=target_uplift,
        window_start=start,
        window_hours=since_hours,
    )


def help_feed_conversion_summary_from_events(
    events: list[Any],
    *,
    target_uplift: float = 0.2,
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    impression_segments: dict[tuple[str, str], str] = {}
    impression_scores: dict[tuple[str, str], int] = {}
    for event in events:
        if getattr(event, "event_type", None) != "help_feed_impression":
            continue
        key = _user_help_event_key(event)
        if key is None:
            continue
        score = _feed_preference_score(getattr(event, "payload_json", None) or {})
        previous = impression_scores.get(key)
        if previous is None or score > previous:
            impression_scores[key] = score
            impression_segments[key] = "matched" if score > 0 else "baseline"

    submitted_keys = {
        key
        for event in events
        if getattr(event, "event_type", None) == "one_liner_submitted"
        for key in [_user_help_event_key(event)]
        if key is not None
    }
    skipped_keys = {
        key
        for event in events
        if getattr(event, "event_type", None) == "help_card_skipped"
        for key in [_user_help_event_key(event)]
        if key is not None
    }

    segments = {
        "matched": _conversion_segment(
            impression_segments,
            submitted_keys,
            skipped_keys,
            segment="matched",
        ),
        "baseline": _conversion_segment(
            impression_segments,
            submitted_keys,
            skipped_keys,
            segment="baseline",
        ),
    }
    matched_rate = float(segments["matched"]["submit_rate"])
    baseline_rate = float(segments["baseline"]["submit_rate"])
    uplift = (matched_rate / baseline_rate - 1.0) if baseline_rate > 0 else None
    impression_keys = set(impression_segments)
    submitted_after_impression = submitted_keys & impression_keys
    skipped_after_impression = skipped_keys & impression_keys
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "target_uplift": target_uplift,
        "segments": segments,
        "matched_submit_rate": matched_rate,
        "baseline_submit_rate": baseline_rate,
        "one_liner_submit_rate": _rate(len(submitted_after_impression), len(impression_keys)),
        "skip_rate": _rate(len(skipped_after_impression), len(impression_keys)),
        "one_liner_submit_rate_uplift": round(uplift, 4) if uplift is not None else None,
        "target_met": bool(uplift is not None and uplift >= target_uplift),
        "total_impression_pairs": len(impression_segments),
        "total_submitted_after_impression": len(submitted_after_impression),
        "total_skipped_after_impression": len(skipped_after_impression),
    }


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
        abuse = _help_card_abuse(help_card)
        if abuse.unsafe:
            _queue_help_card_review_task(
                session,
                help_card=help_card,
                reason=abuse.reason or "unsafe",
                issues=abuse.issues,
                priority=abuse.priority,
                payload=payload,
                abuse=abuse,
            )
            session.commit()
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "help_card_unsafe",
                    "reason": abuse.reason,
                    "issues": list(abuse.issues),
                },
            )
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
        abuse = detect_one_liner_abuse(text)
        if abuse.unsafe:
            _queue_one_liner_review_task(
                session,
                help_card=help_card,
                raw_text=text,
                reason=abuse.reason or "unsafe",
                issues=abuse.issues,
                priority=abuse.priority,
                payload=payload,
                abuse=abuse,
                quality=None,
            )
            session.commit()
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "one_liner_unsafe",
                    "reason": abuse.reason,
                    "issues": list(abuse.issues),
                },
            )
        quality = assess_one_liner_quality(text)
        if not quality.accepted:
            _queue_one_liner_review_task(
                session,
                help_card=help_card,
                raw_text=text,
                reason=quality.reason or "low_quality",
                issues=quality.issues,
                priority=70,
                payload=payload,
                abuse=None,
                quality=quality,
            )
            session.commit()
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


def skip_help_card(id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(id))
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        device_uid = payload.get("device_uid") or payload.get("device_id") or payload.get("user_id")
        user_id = payload.get("user_id")
        if not device_uid and not user_id:
            raise HTTPException(status_code=422, detail="device_uid_or_user_id_required")
        user = ensure_user(session, device_uid=device_uid, user_id=user_id)
        if user.id == help_card.owner_user_id:
            raise HTTPException(status_code=403, detail="owner_cannot_skip_own_help_card")
        event = record_user_behavior_event(
            session,
            event_type="help_card_skipped",
            user_id=user.id,
            conversation_id=help_card.conversation_id,
            help_card_id=help_card.id,
            source="help_feed",
            payload_json={
                **dict(payload.get("metadata") or {}),
                "reason": str(payload.get("reason") or "").strip() or None,
            },
        )
        session.flush()
        return {
            "ok": True,
            "help_card_id": str(help_card.id),
            "event": serialize_user_behavior_event(event),
        }


def accept_final_recommendation(id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(id))
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        final_card = help_card.final_recommendation_card
        if final_card is None:
            raise HTTPException(status_code=409, detail="final_recommendation_not_ready")

        previous_status = final_card.status
        final_card.status = "accepted"
        final_card.accepted_at = utcnow()
        if help_card.question is not None:
            help_card.question.status = "completed"
            help_card.question.current_recommendation_card_id = final_card.id

        event = record_user_behavior_event(
            session,
            event_type="final_recommendation_accepted",
            user_id=uuid.UUID(str(payload["user_id"])) if payload.get("user_id") else help_card.owner_user_id,
            device_uid=payload.get("device_uid") or payload.get("device_id"),
            conversation_id=help_card.conversation_id,
            recommendation_card_id=final_card.id,
            help_card_id=help_card.id,
            source="help_final",
            payload_json={
                **dict(payload.get("metadata") or {}),
                "action": "accept_final",
                "status": "final_accepted",
                "previous_card_status": previous_status,
                "reason": str(payload.get("reason") or "").strip() or None,
            },
        )
        session.flush()
        return {
            "help_card_id": str(help_card.id),
            "card_id": str(final_card.id),
            "accepted": True,
            "feedback": {
                "action": "accept_final",
                "status": "final_accepted",
                "previous_card_status": previous_status,
            },
            "event": serialize_user_behavior_event(event),
            "metadata": {"status": "final_accepted"},
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
            "items": [_serialize_reward_event(event) for event in rows],
        }


def _queue_one_liner_review_task(
    session: Any,
    *,
    help_card: HelpCard,
    raw_text: str,
    reason: str,
    issues: tuple[str, ...],
    priority: int,
    payload: dict[str, Any],
    abuse: OneLinerAbuseCheck | None,
    quality: OneLinerQuality | None,
) -> None:
    session.add(
        ContentReviewTask(
            task_type="one_liner_rejected",
            status="open",
            priority=priority,
            target_table="help_cards",
            target_record_id=str(help_card.id),
            title=f"Rejected one-liner for {help_card.title}",
            reason=reason,
            payload_json={
                "source": "one_liner",
                "help_card_id": str(help_card.id),
                "help_card_title": help_card.title,
                "device_uid": payload.get("device_uid") or payload.get("device_id") or payload.get("user_id"),
                "user_id": payload.get("user_id"),
                "raw_text": raw_text,
                "reason": reason,
                "issues": list(issues),
                "abuse": {
                    "unsafe": abuse.unsafe,
                    "reason": abuse.reason,
                    "issues": list(abuse.issues),
                    "priority": abuse.priority,
                }
                if abuse is not None
                else None,
                "quality": one_liner_quality_metadata(quality) if quality is not None else None,
                "metadata": dict(payload.get("metadata") or {}),
            },
        )
    )
    session.flush()


def _queue_help_card_review_task(
    session: Any,
    *,
    help_card: HelpCard,
    reason: str,
    issues: tuple[str, ...],
    priority: int,
    payload: dict[str, Any],
    abuse: HelpCardAbuseCheck,
) -> None:
    existing = session.scalar(
        select(ContentReviewTask).where(
            ContentReviewTask.task_type == "help_card_rejected",
            ContentReviewTask.target_table == "help_cards",
            ContentReviewTask.target_record_id == str(help_card.id),
            ContentReviewTask.status == "open",
        )
    )
    if existing is not None:
        existing.reason = reason
        existing.priority = min(int(existing.priority or priority), int(priority))
        existing.payload_json = {
            **dict(existing.payload_json or {}),
            "reason": reason,
            "issues": list(issues),
            "abuse": _help_card_abuse_payload(abuse),
            "metadata": dict(payload.get("metadata") or {}),
        }
        session.flush()
        return
    session.add(
        ContentReviewTask(
            task_type="help_card_rejected",
            status="open",
            priority=priority,
            target_table="help_cards",
            target_record_id=str(help_card.id),
            title=f"Unsafe help card blocked: {help_card.title}",
            reason=reason,
            payload_json={
                "source": "help_card_publish",
                "help_card_id": str(help_card.id),
                "help_card_title": help_card.title,
                "context_text": help_card.context_text,
                "reason": reason,
                "issues": list(issues),
                "abuse": _help_card_abuse_payload(abuse),
                "metadata": dict(payload.get("metadata") or {}),
            },
        )
    )
    session.flush()


def _help_card_abuse(help_card: HelpCard) -> HelpCardAbuseCheck:
    return detect_help_card_abuse(
        title=str(help_card.title or ""),
        context_text=str(help_card.context_text or ""),
        payload=help_card.payload_json or {},
    )


def _help_card_abuse_payload(abuse: HelpCardAbuseCheck) -> dict[str, Any]:
    return {
        "unsafe": abuse.unsafe,
        "reason": abuse.reason,
        "issues": list(abuse.issues),
        "priority": abuse.priority,
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


def _serialize_reward_event(event: RewardEvent) -> dict[str, Any]:
    payload = dict(event.payload_json or {})
    settlement_reason = _non_empty_string(payload.get("settlement_reason"))
    final_card_id = _non_empty_string(payload.get("final_recommendation_card_id"))
    return {
        "id": str(event.id),
        "type": event.event_type,
        "label": event.label,
        "value": event.value,
        "status": event.status,
        "help_card_id": str(event.help_card_id) if event.help_card_id else None,
        "help_answer_id": str(event.help_answer_id) if event.help_answer_id else None,
        "final_recommendation_card_id": final_card_id,
        "settlement_reason": settlement_reason,
        "used_as_final_evidence": _is_used_as_final_evidence(
            reward_status=event.status,
            settlement_reason=settlement_reason,
        ),
        "created_at": event.created_at,
    }


def _help_answer_settlement_payload(answer: HelpAnswer) -> dict[str, Any]:
    reward_events = sorted(
        list(answer.reward_events or []),
        key=lambda event: event.created_at,
        reverse=True,
    )
    for event in reward_events:
        payload = dict(event.payload_json or {})
        final_card_id = _non_empty_string(payload.get("final_recommendation_card_id"))
        settlement_reason = _non_empty_string(payload.get("settlement_reason"))
        if final_card_id or settlement_reason:
            return {
                "final_recommendation_card_id": final_card_id,
                "settlement_reason": settlement_reason,
                "used_as_final_evidence": _is_used_as_final_evidence(
                    reward_status=answer.reward_status,
                    answer_status=answer.status,
                    settlement_reason=settlement_reason,
                ),
            }

    help_card = answer.help_card
    final_card_id = (
        str(help_card.final_recommendation_card_id)
        if help_card is not None and help_card.final_recommendation_card_id
        else None
    )
    fallback_reason = _settlement_reason_from_answer_status(answer) if final_card_id else None
    return {
        "final_recommendation_card_id": final_card_id,
        "settlement_reason": fallback_reason,
        "used_as_final_evidence": _is_used_as_final_evidence(
            reward_status=answer.reward_status,
            answer_status=answer.status,
            settlement_reason=fallback_reason,
        ),
    }


def _settlement_reason_from_answer_status(answer: HelpAnswer) -> str | None:
    if answer.reward_status == "granted" or answer.status == "used":
        return "used_as_final_evidence"
    if answer.reward_status == "rejected" or answer.status == "rejected":
        return "not_selected_for_final_answer"
    return None


def _is_used_as_final_evidence(
    *,
    reward_status: str | None = None,
    answer_status: str | None = None,
    settlement_reason: str | None = None,
) -> bool:
    return (
        settlement_reason == "used_as_final_evidence"
        or reward_status == "granted"
        or answer_status == "used"
    )


def _non_empty_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _serialize_ranked_help_card(
    help_card: HelpCard,
    *,
    answerer_preferences: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    item = serialize_help_card(help_card)
    metadata = dict(item.get("metadata") or {})
    metadata["feed_ranking"] = help_feed_rank_payload(
        help_card,
        answerer_preferences=answerer_preferences,
    )
    item["metadata"] = metadata
    return item


def _serialize_help_answer(answer: HelpAnswer) -> dict[str, Any]:
    help_card = answer.help_card
    reward = dict((answer.evidence_json or {}).get("reward") or {})
    if not reward and help_card is not None:
        reward = _reward_payload(help_card)
    settlement = _help_answer_settlement_payload(answer)
    return {
        "id": str(answer.id),
        "help_card_id": str(answer.help_card_id),
        "raw_text": answer.raw_text,
        "status": answer.status,
        "reward_status": answer.reward_status,
        "question_title": str(getattr(help_card, "title", None) or "求一个"),
        "question_context": str(getattr(help_card, "context_text", None) or ""),
        "reward": reward,
        **settlement,
        "created_at": answer.created_at,
    }


def help_feed_rank_payload(
    help_card: HelpCard,
    *,
    answerer_preferences: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    answer_count = int(getattr(help_card, "answer_count", 0) or 0)
    min_required = int(getattr(help_card, "min_answers_required", 3) or 3)
    reward_value = _help_card_reward_value(help_card)
    remaining_answers = max(0, min_required - answer_count)
    preference_match = _answerer_preference_match_payload(help_card, answerer_preferences)
    return {
        "reward_value": reward_value,
        "answer_count": answer_count,
        "min_answers_required": min_required,
        "remaining_answers": remaining_answers,
        "preference_match": preference_match,
        "score": _help_feed_score(
            reward_value=reward_value,
            remaining_answers=remaining_answers,
            answer_count=answer_count,
            preference_score=int(preference_match["score"]),
        ),
    }


def help_feed_sort_key(
    help_card: HelpCard,
    *,
    answerer_preferences: Mapping[str, Any] | None = None,
) -> tuple[float, int, int, float, float]:
    rank = help_feed_rank_payload(help_card, answerer_preferences=answerer_preferences)
    published_ts = _timestamp(getattr(help_card, "published_at", None))
    created_ts = _timestamp(getattr(help_card, "created_at", None))
    return (
        -float(rank["score"]),
        -int(rank["reward_value"]),
        int(rank["answer_count"]),
        -published_ts,
        -created_ts,
    )


def _help_feed_score(
    *,
    reward_value: int,
    remaining_answers: int,
    answer_count: int,
    preference_score: int = 0,
) -> float:
    return float(reward_value * 100 + remaining_answers * 20 - answer_count * 5 + preference_score)


def _user_help_event_key(event: Any) -> tuple[str, str] | None:
    user_id = getattr(event, "user_id", None)
    help_card_id = getattr(event, "help_card_id", None)
    if user_id is None or help_card_id is None:
        return None
    return (str(user_id), str(help_card_id))


def _feed_preference_score(payload: Mapping[str, Any]) -> int:
    ranking = payload.get("feed_ranking") if isinstance(payload.get("feed_ranking"), Mapping) else {}
    match = ranking.get("preference_match") if isinstance(ranking.get("preference_match"), Mapping) else {}
    try:
        return int(match.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _conversion_segment(
    impression_segments: Mapping[tuple[str, str], str],
    submitted_keys: set[tuple[str, str]],
    skipped_keys: set[tuple[str, str]],
    *,
    segment: str,
) -> dict[str, Any]:
    impression_keys = {key for key, value in impression_segments.items() if value == segment}
    submitted = len(impression_keys & submitted_keys)
    skipped = len(impression_keys & skipped_keys)
    impressions = len(impression_keys)
    submit_rate = submitted / impressions if impressions else 0.0
    skip_rate = skipped / impressions if impressions else 0.0
    return {
        "impression_pairs": impressions,
        "submitted_pairs": submitted,
        "skipped_pairs": skipped,
        "submit_rate": round(submit_rate, 4),
        "skip_rate": round(skip_rate, 4),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _answerer_preference_summary(user: Any | None) -> dict[str, Any]:
    if user is None:
        return {}
    profile = dict(getattr(user, "profile_json", None) or {})
    memory = profile.get(PREFERENCE_PROFILE_KEY)
    if not isinstance(memory, Mapping):
        return {}
    summary = memory.get("summary")
    return dict(summary) if isinstance(summary, Mapping) else {}


def _answerer_preference_match_payload(
    help_card: HelpCard,
    answerer_preferences: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not answerer_preferences:
        return {"score": 0, "matched": {}, "candidate_terms": []}

    haystack = _help_card_match_text(help_card)
    matched: dict[str, list[str]] = {}
    score = 0
    weights = {
        "top_cuisines": 35,
        "top_food_items": 35,
        "taste_preferences": 25,
        "spice_preferences": 25,
        "budget_preferences": 15,
        "companions": 15,
        "areas": 20,
        "accepted_items": 20,
    }
    for preference_key, weight in weights.items():
        values = _preference_values(answerer_preferences.get(preference_key))
        hits = [value for value in values if value and value in haystack]
        if not hits:
            continue
        matched[preference_key] = hits
        score += weight * len(hits)

    return {
        "score": score,
        "matched": matched,
        "candidate_terms": _help_card_candidate_terms(help_card),
    }


def _help_card_match_text(help_card: HelpCard) -> str:
    payload = getattr(help_card, "payload_json", None) or {}
    parts: list[str] = [
        str(getattr(help_card, "title", "") or ""),
        str(getattr(help_card, "prompt", "") or ""),
        str(getattr(help_card, "context_text", "") or ""),
    ]
    if isinstance(payload, Mapping):
        for key in ("context", "wants", "avoids", "constraints"):
            parts.extend(_flatten_text_values(payload.get(key)))
    return " ".join(part for part in parts if part)


def _help_card_candidate_terms(help_card: HelpCard) -> list[str]:
    text = _help_card_match_text(help_card)
    candidates = [
        "韩餐",
        "川菜",
        "粤菜",
        "火锅",
        "热干面",
        "烤鸭",
        "清淡",
        "不辣",
        "预算",
        "朋友",
        "爸妈",
        "约会",
        "五道口",
        "三里屯",
        "朝阳区",
        "望京",
        "国贸",
    ]
    return [term for term in candidates if term in text]


def _preference_values(value: Any) -> list[str]:
    values: list[Any]
    if isinstance(value, Mapping):
        values = [value.get("value")]
    elif isinstance(value, list):
        values = [item.get("value") if isinstance(item, Mapping) else item for item in value]
    else:
        values = [value]
    cleaned: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _flatten_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        parts: list[str] = []
        for nested in value.values():
            parts.extend(_flatten_text_values(nested))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for nested in value:
            parts.extend(_flatten_text_values(nested))
        return parts
    return [str(value)]


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
    "help_feed_conversion_summary",
    "help_feed_conversion_summary_from_events",
    "help_feed_rank_payload",
    "help_feed_sort_key",
    "list_help_feed",
    "list_my_help_answers",
    "list_my_help_cards",
    "publish_help_card",
    "accept_final_recommendation",
    "skip_help_card",
]
