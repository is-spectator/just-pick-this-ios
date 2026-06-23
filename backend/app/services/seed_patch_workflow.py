"""Ops workflow for turning accepted seed patches into IntentAnswer drafts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, Intent, IntentAnswer


OPS_SEED_PATCH_SOURCE_TYPE = "ops_seed_patch"


def latest_accepted_seed_patch(
    session: Session,
    *,
    run_id: str,
    case_id: str,
) -> dict[str, Any] | None:
    """Return the latest accepted seed patch for an eval case review."""

    target = f"{run_id}:{case_id}"
    audits = session.scalars(
        select(AdminAuditLog)
        .where(
            AdminAuditLog.action == "review_eval_case",
            AdminAuditLog.target_table == "eval_run_cases",
            AdminAuditLog.target_record_id == target,
        )
        .order_by(AdminAuditLog.created_at.desc())
    ).all()
    for audit in audits:
        payload = audit.after_json or {}
        if payload.get("action") != "accept_seed_gap":
            continue
        seed_patch = payload.get("seed_patch")
        if isinstance(seed_patch, Mapping):
            return dict(seed_patch)
    return None


def create_seed_intent_answer_draft(
    session: Session,
    *,
    run_id: str,
    case_id: str,
    seed_patch: Mapping[str, Any],
    reviewer: str,
) -> IntentAnswer:
    """Create or update an inactive IntentAnswer draft from an ops seed patch."""

    patch = dict(seed_patch)
    intent_key = str(patch.get("intent_key") or "").strip()
    if not intent_key:
        raise ValueError("seed_patch.intent_key required")

    source_ref_id = f"{run_id}:{case_id}"
    intent = _upsert_intent(session, intent_key=intent_key, seed_patch=patch)
    answer = session.scalar(
        select(IntentAnswer).where(
            IntentAnswer.source_type == OPS_SEED_PATCH_SOURCE_TYPE,
            IntentAnswer.source_ref_id == source_ref_id,
        )
    )
    if answer is None:
        answer = IntentAnswer(
            intent_id=intent.id,
            source_type=OPS_SEED_PATCH_SOURCE_TYPE,
            source_ref_id=source_ref_id,
            answer_text=_answer_summary(patch),
        )
        session.add(answer)

    constraints = _constraints_from_patch(patch)
    answer.intent_id = intent.id
    answer.intent_key = intent.key
    answer.intent_text = str(patch.get("intent_text") or intent.name)
    answer.answer_title = _answer_title(patch)
    answer.answer_summary = _answer_summary(patch)
    answer.answer_text = _answer_summary(patch)
    answer.constraints_json = constraints
    answer.confidence = _confidence(patch)
    answer.last_used_at = None
    answer.locale = str(patch.get("locale") or "zh-CN")
    answer.priority = int(patch.get("priority") or 80)
    answer.tags_json = _tags_from_patch(patch)
    answer.evidence_json = {
        "source_type": OPS_SEED_PATCH_SOURCE_TYPE,
        "source_ref_id": source_ref_id,
        "run_id": run_id,
        "case_id": case_id,
        "reviewer": reviewer,
        "seed_patch": patch,
        "approved": False,
        "draft": True,
        "created_by": "admin_seed_patch_workflow",
    }
    # Draft rows must not affect product retrieval until a later explicit publish step.
    answer.is_active = False
    session.flush()
    return answer


def serialize_seed_intent_answer_draft(answer: IntentAnswer) -> dict[str, Any]:
    return {
        "id": str(answer.id),
        "intent_id": str(answer.intent_id),
        "intent_key": answer.intent_key,
        "intent_text": answer.intent_text,
        "answer_title": answer.answer_title,
        "answer_summary": answer.answer_summary,
        "source_type": answer.source_type,
        "source_ref_id": answer.source_ref_id,
        "is_active": answer.is_active,
        "priority": answer.priority,
        "constraints": answer.constraints_json,
        "evidence": answer.evidence_json,
    }


def _upsert_intent(session: Session, *, intent_key: str, seed_patch: Mapping[str, Any]) -> Intent:
    intent = session.scalar(select(Intent).where(Intent.key == intent_key))
    if intent is None:
        intent = Intent(key=intent_key, name=_intent_name(seed_patch), description="Ops seed patch draft")
        session.add(intent)
    intent.name = _intent_name(seed_patch)
    intent.description = str(seed_patch.get("intent_description") or intent.description or "Ops seed patch draft")
    intent.is_active = True
    session.flush()
    return intent


def _intent_name(seed_patch: Mapping[str, Any]) -> str:
    explicit = str(seed_patch.get("intent_text") or seed_patch.get("intent_name") or "").strip()
    if explicit:
        return explicit
    parts = [
        seed_patch.get("city"),
        seed_patch.get("area") or seed_patch.get("venue"),
        seed_patch.get("food_item") or seed_patch.get("cuisine") or seed_patch.get("task"),
    ]
    text = " ".join(str(part) for part in parts if part)
    return text or str(seed_patch.get("intent_key") or "Ops seed patch")


def _answer_title(seed_patch: Mapping[str, Any]) -> str:
    explicit = str(seed_patch.get("answer_title") or seed_patch.get("title") or "").strip()
    if explicit:
        return explicit
    place = seed_patch.get("venue") or seed_patch.get("area") or seed_patch.get("city")
    item = seed_patch.get("food_item") or seed_patch.get("cuisine") or seed_patch.get("target_type")
    title = "".join(str(part) for part in (place, item) if part)
    return title or "待补全 seed answer"


def _answer_summary(seed_patch: Mapping[str, Any]) -> str:
    explicit = str(
        seed_patch.get("answer_summary")
        or seed_patch.get("summary")
        or seed_patch.get("answer_text")
        or ""
    ).strip()
    if explicit:
        return explicit
    return "运营待补全的 seed answer 草稿。"


def _constraints_from_patch(seed_patch: Mapping[str, Any]) -> dict[str, Any]:
    reserved = {
        "intent_key",
        "intent_text",
        "intent_name",
        "intent_description",
        "answer_title",
        "title",
        "answer_summary",
        "summary",
        "answer_text",
        "confidence",
        "priority",
        "locale",
    }
    return {str(key): value for key, value in seed_patch.items() if key not in reserved}


def _tags_from_patch(seed_patch: Mapping[str, Any]) -> list[str]:
    tags = ["ops_seed_patch", "draft"]
    for key in ("domain", "location_state", "target_type", "city", "area", "venue", "food_item", "cuisine"):
        value = seed_patch.get(key)
        if value:
            tags.append(str(value))
    return list(dict.fromkeys(tags))


def _confidence(seed_patch: Mapping[str, Any]) -> float | None:
    value = seed_patch.get("confidence")
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(parsed, 1.0))


__all__ = [
    "OPS_SEED_PATCH_SOURCE_TYPE",
    "create_seed_intent_answer_draft",
    "latest_accepted_seed_patch",
    "serialize_seed_intent_answer_draft",
]
