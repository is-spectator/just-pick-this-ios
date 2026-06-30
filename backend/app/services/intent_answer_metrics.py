"""Operational metrics for IntentAnswer memory quality."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntentAnswer, RecommendationCard


def intent_answer_memory_summary(session: Session, *, top_limit: int = 20) -> dict[str, Any]:
    answers = list(session.scalars(select(IntentAnswer)).all())
    cards = list(session.scalars(select(RecommendationCard)).all())

    answer_ids = {str(answer.id) for answer in answers}
    referenced_answer_ids = [_card_intent_answer_id(card) for card in cards]
    referenced_answer_ids = [answer_id for answer_id in referenced_answer_ids if answer_id in answer_ids]
    referenced_unique_ids = set(referenced_answer_ids)

    success_total = sum(int(answer.success_count or 0) for answer in answers)
    rejection_total = sum(int(answer.rejection_count or 0) for answer in answers)
    feedback_total = success_total + rejection_total
    active_count = sum(1 for answer in answers if answer.is_active)
    confidence_values = [float(answer.confidence) for answer in answers if answer.confidence is not None]
    source_counts = Counter(str(answer.source_type or "unknown") for answer in answers)
    top_answers = sorted(
        answers,
        key=lambda answer: (
            -(int(answer.success_count or 0) + int(answer.rejection_count or 0)),
            -int(answer.success_count or 0),
            str(answer.intent_key or answer.id),
        ),
    )[: max(1, int(top_limit or 1))]
    return {
        "total_intent_answer_count": len(answers),
        "active_intent_answer_count": active_count,
        "draft_intent_answer_count": max(0, len(answers) - active_count),
        "source_type_counts": dict(sorted(source_counts.items())),
        "recommendation_card_count": len(cards),
        "intent_answer_reference_count": len(referenced_answer_ids),
        "referenced_intent_answer_count": len(referenced_unique_ids),
        "intent_answer_hit_rate": round(len(referenced_answer_ids) / len(cards), 4) if cards else 0.0,
        "referenced_answer_coverage_rate": (
            round(len(referenced_unique_ids) / len(answers), 4) if answers else 0.0
        ),
        "success_count": success_total,
        "rejection_count": rejection_total,
        "accepted_intent_rate": round(success_total / feedback_total, 4) if feedback_total else 0.0,
        "last_used_count": sum(1 for answer in answers if answer.last_used_at is not None),
        "average_confidence": round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0,
        "top_answers": [_serialize_intent_answer_metric(answer) for answer in top_answers],
        "metadata": {
            "version": "intent_answer_memory_summary_v1",
            "contract": "measure active memory, card references, acceptance/rejection feedback, and source mix",
        },
    }


def _card_intent_answer_id(card: RecommendationCard) -> str | None:
    payload = dict(card.payload_json or {})
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    for value in (
        payload.get("intent_answer_id"),
        payload.get("reference_intent_answer_id"),
        provenance.get("source_answer_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return None


def _serialize_intent_answer_metric(answer: IntentAnswer) -> dict[str, Any]:
    return {
        "id": str(answer.id),
        "intent_key": answer.intent_key,
        "answer_title": answer.answer_title,
        "source_type": answer.source_type,
        "is_active": answer.is_active,
        "priority": answer.priority,
        "confidence": answer.confidence,
        "success_count": int(answer.success_count or 0),
        "rejection_count": int(answer.rejection_count or 0),
        "last_used_at": answer.last_used_at.isoformat() if answer.last_used_at else None,
    }


__all__ = ["intent_answer_memory_summary"]
