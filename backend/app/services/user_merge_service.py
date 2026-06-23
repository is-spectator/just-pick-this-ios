from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    AuthAuditLog,
    Conversation,
    HelpAnswer,
    HelpCard,
    LightEvent,
    Question,
    RecommendationCard,
    RewardEvent,
    Turn,
    User,
    UserDevice,
)
from app.services.runtime import utcnow


def bind_device_to_user(
    session: Session,
    *,
    user: User,
    device_uid: str | None,
    platform: str | None = None,
    app_version: str | None = None,
) -> UserDevice | None:
    normalized = _normalize_device_uid(device_uid)
    if normalized is None:
        return None

    existing = session.scalar(select(UserDevice).where(UserDevice.device_uid == normalized))
    now = utcnow()
    if existing is not None:
        if existing.user_id != user.id:
            raise HTTPException(status_code=409, detail="device_uid already bound to another account")
        existing.platform = platform or existing.platform
        existing.app_version = app_version or existing.app_version
        existing.last_seen_at = now
        return existing

    device = UserDevice(
        user_id=user.id,
        device_uid=normalized,
        platform=platform,
        app_version=app_version,
        last_seen_at=now,
    )
    session.add(device)
    return device


def merge_device_user_into_email_user(
    session: Session,
    *,
    device_uid: str | None,
    email_user: User,
    platform: str | None = None,
    app_version: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_device_uid(device_uid)
    bind_device_to_user(
        session,
        user=email_user,
        device_uid=normalized,
        platform=platform,
        app_version=app_version,
    )
    if normalized is None:
        return {"merged": False, "reason": "no_device_uid"}

    anonymous = session.scalar(select(User).where(User.device_uid == normalized))
    if anonymous is None or anonymous.id == email_user.id:
        return {"merged": False, "reason": "no_anonymous_user"}
    if anonymous.email and anonymous.email != email_user.email:
        raise HTTPException(status_code=409, detail="device_uid belongs to another email account")

    counts: dict[str, int] = {}
    for label, statement in (
        ("conversations", update(Conversation).where(Conversation.user_id == anonymous.id).values(user_id=email_user.id)),
        ("turns", update(Turn).where(Turn.user_id == anonymous.id).values(user_id=email_user.id)),
        ("questions", update(Question).where(Question.user_id == anonymous.id).values(user_id=email_user.id)),
        (
            "recommendation_cards",
            update(RecommendationCard).where(RecommendationCard.user_id == anonymous.id).values(user_id=email_user.id),
        ),
        (
            "help_cards",
            update(HelpCard).where(HelpCard.owner_user_id == anonymous.id).values(owner_user_id=email_user.id),
        ),
        (
            "help_answers",
            update(HelpAnswer).where(HelpAnswer.answer_user_id == anonymous.id).values(answer_user_id=email_user.id),
        ),
        (
            "light_events",
            update(LightEvent).where(LightEvent.user_id == anonymous.id).values(user_id=email_user.id),
        ),
        (
            "reward_events",
            update(RewardEvent).where(RewardEvent.user_id == anonymous.id).values(user_id=email_user.id),
        ),
        (
            "auth_audit_logs",
            update(AuthAuditLog).where(AuthAuditLog.user_id == anonymous.id).values(user_id=email_user.id),
        ),
    ):
        result = session.execute(statement)
        counts[label] = int(result.rowcount or 0)

    anonymous.status = "merged"
    anonymous.auth_provider = "merged"
    anonymous.profile_json = {
        **dict(anonymous.profile_json or {}),
        "merged_into_user_id": str(email_user.id),
        "merged_at": utcnow().isoformat(),
    }
    return {
        "merged": True,
        "anonymous_user_id": str(anonymous.id),
        "target_user_id": str(email_user.id),
        "counts": counts,
    }


def _normalize_device_uid(device_uid: str | None) -> str | None:
    if device_uid is None:
        return None
    stripped = device_uid.strip()
    return stripped or None
