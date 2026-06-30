"""Admin workflow for importing IntentAnswer drafts safely."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Intent, IntentAnswer


ADMIN_INTENT_ANSWER_IMPORT_SOURCE_TYPE = "admin_intent_answer_import"


def import_intent_answer_drafts(
    session: Session,
    *,
    items: Sequence[Mapping[str, Any]],
    reviewer: str,
    activate: bool = False,
) -> list[IntentAnswer]:
    """Create or update inactive IntentAnswer drafts from ops-provided rows.

    Rows are idempotent by ``source_type`` + ``source_ref_id``. By default imports are
    inactive drafts so product retrieval is not affected until a human explicitly
    activates the row through the normal admin table editor.
    """

    answers: list[IntentAnswer] = []
    for index, raw_item in enumerate(items):
        item = dict(raw_item)
        intent_key = _required_text(item, "intent_key", index=index)
        answer_title = _required_text(item, "answer_title", index=index)
        answer_summary = _required_text(item, "answer_summary", index=index)
        source_type = str(item.get("source_type") or ADMIN_INTENT_ANSWER_IMPORT_SOURCE_TYPE).strip()
        if not source_type:
            source_type = ADMIN_INTENT_ANSWER_IMPORT_SOURCE_TYPE
        source_ref_id = str(item.get("source_ref_id") or _source_ref_id(item)).strip()

        intent = _upsert_import_intent(session, item=item, intent_key=intent_key)
        answer = session.scalar(
            select(IntentAnswer).where(
                IntentAnswer.source_type == source_type,
                IntentAnswer.source_ref_id == source_ref_id,
            )
        )
        if answer is None:
            answer = IntentAnswer(
                intent_id=intent.id,
                source_type=source_type,
                source_ref_id=source_ref_id,
                answer_text=answer_summary,
            )
            session.add(answer)

        answer.intent_id = intent.id
        answer.intent_key = intent.key
        answer.intent_text = str(item.get("intent_text") or intent.name)
        answer.answer_title = answer_title
        answer.answer_summary = answer_summary
        answer.answer_text = answer_summary
        answer.constraints_json = _object(item.get("constraints") or item.get("constraints_json"), field="constraints")
        answer.confidence = _confidence(item.get("confidence"))
        answer.locale = str(item.get("locale") or "zh-CN")
        answer.priority = int(item.get("priority") or 70)
        answer.tags_json = _tags(item)
        answer.evidence_json = {
            "source_type": source_type,
            "source_ref_id": source_ref_id,
            "reviewer": reviewer,
            "approved": False,
            "draft": not activate,
            "created_by": "admin_intent_answer_import",
            "import_row": item,
        }
        answer.is_active = bool(activate and item.get("is_active", True))
        answers.append(answer)

    session.flush()
    return answers


def serialize_imported_intent_answer(answer: IntentAnswer) -> dict[str, Any]:
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
        "confidence": answer.confidence,
        "constraints": answer.constraints_json,
        "tags": answer.tags_json,
        "evidence": answer.evidence_json,
    }


def _upsert_import_intent(session: Session, *, item: Mapping[str, Any], intent_key: str) -> Intent:
    intent = session.scalar(select(Intent).where(Intent.key == intent_key))
    if intent is None:
        intent = Intent(key=intent_key, name=_intent_name(item), description="Admin IntentAnswer import draft")
        session.add(intent)
    intent.name = _intent_name(item)
    intent.description = str(item.get("intent_description") or intent.description or "Admin IntentAnswer import draft")
    intent.is_active = True
    session.flush()
    return intent


def _intent_name(item: Mapping[str, Any]) -> str:
    explicit = str(item.get("intent_text") or item.get("intent_name") or "").strip()
    if explicit:
        return explicit
    parts = [
        item.get("city"),
        item.get("area") or item.get("venue"),
        item.get("food_item") or item.get("cuisine") or item.get("task"),
    ]
    return " ".join(str(part) for part in parts if part) or str(item.get("intent_key") or "Imported intent")


def _required_text(item: Mapping[str, Any], field: str, *, index: int) -> str:
    value = str(item.get(field) or "").strip()
    if not value:
        raise ValueError(f"items[{index}].{field} required")
    return value


def _source_ref_id(item: Mapping[str, Any]) -> str:
    basis = "|".join(
        str(item.get(key) or "")
        for key in ("intent_key", "answer_title", "answer_summary", "city", "area", "venue", "food_item", "cuisine")
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"admin-import:{digest}"


def _object(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _tags(item: Mapping[str, Any]) -> list[str]:
    raw_tags = item.get("tags") or item.get("tags_json") or []
    tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else [str(raw_tags)]
    tags.append("admin_import")
    for key in ("domain", "location_state", "target_type", "city", "area", "venue", "food_item", "cuisine"):
        value = item.get(key)
        if value:
            tags.append(str(value))
    return list(dict.fromkeys(tag for tag in tags if tag))


def _confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(parsed, 1.0))


__all__ = [
    "ADMIN_INTENT_ANSWER_IMPORT_SOURCE_TYPE",
    "import_intent_answer_drafts",
    "serialize_imported_intent_answer",
]
