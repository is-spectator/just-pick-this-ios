"""Operational metrics for help-card finalization quality."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpCard, IntentAnswer, LightEvent, RecommendationCard


def finalizer_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    help_cards = session.scalars(
        select(HelpCard).where(HelpCard.created_at >= start).order_by(HelpCard.created_at.asc())
    ).all()
    final_card_ids = {
        _record_id_from_value(getattr(help_card, "final_recommendation_card_id", None))
        for help_card in help_cards
        if getattr(help_card, "final_recommendation_card_id", None) is not None
    }
    final_cards = (
        session.scalars(select(RecommendationCard).where(RecommendationCard.id.in_(final_card_ids))).all()
        if final_card_ids
        else []
    )
    intent_answers = session.scalars(
        select(IntentAnswer).where(
            IntentAnswer.source_type == "help_final",
            IntentAnswer.created_at >= start,
        )
    ).all()
    light_events = session.scalars(
        select(LightEvent).where(
            LightEvent.type == "final_ready",
            LightEvent.created_at >= start,
        )
    ).all()
    return finalizer_summary_from_records(
        help_cards=help_cards,
        final_cards=final_cards,
        intent_answers=intent_answers,
        light_events=light_events,
        window_start=start,
        window_hours=since_hours,
    )


def finalizer_summary_from_records(
    *,
    help_cards: list[Any],
    final_cards: list[Any],
    intent_answers: list[Any],
    light_events: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    final_card_by_id = {_record_id(card): card for card in final_cards if _record_id(card)}
    help_final_intents_by_ref = _group_by_source_ref(intent_answers)
    light_help_ids = {_light_help_card_id(event) for event in light_events if _light_help_card_id(event)}

    ready_cards = [_card for _card in help_cards if _is_ready_for_finalization(_card)]
    finalized_cards = [_card for _card in help_cards if _final_card_id(_card)]
    ready_without_final = [_card for _card in ready_cards if not _final_card_id(_card)]

    quality_items: list[dict[str, Any]] = []
    for help_card in finalized_cards:
        help_card_id = _record_id(help_card)
        final_card_id = _final_card_id(help_card)
        final_card = final_card_by_id.get(final_card_id)
        issues = _final_card_quality_issues(
            help_card=help_card,
            final_card=final_card,
            intent_answers=help_final_intents_by_ref.get(help_card_id or "", []),
            has_light_event=help_card_id in light_help_ids,
        )
        quality_items.append(
            {
                "help_card_id": help_card_id,
                "final_recommendation_card_id": final_card_id,
                "passed": not issues,
                "issues": issues,
            }
        )

    quality_pass_count = sum(1 for item in quality_items if item["passed"])
    intent_answer_writeback_count = sum(
        1 for intent_answer in intent_answers if str(getattr(intent_answer, "source_type", "") or "") == "help_final"
    )
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "counts": {
            "help_card_count": len(help_cards),
            "ready_help_card_count": len(ready_cards),
            "finalized_help_card_count": len(finalized_cards),
            "ready_without_final_count": len(ready_without_final),
            "final_card_quality_pass_count": quality_pass_count,
            "final_card_quality_fail_count": max(0, len(quality_items) - quality_pass_count),
            "intent_answer_writeback_count": intent_answer_writeback_count,
            "light_event_count": len(light_help_ids),
        },
        "rates": {
            "finalization_rate": _rate(len(finalized_cards), len(ready_cards)),
            "help_final_quality": _rate(quality_pass_count, len(quality_items)),
            "intent_answer_writeback_rate": _rate(intent_answer_writeback_count, len(finalized_cards)),
            "light_event_rate": _rate(len(light_help_ids), len(finalized_cards)),
        },
        "ready_without_final_items": [
            {
                "help_card_id": _record_id(help_card),
                "title": str(getattr(help_card, "title", "") or ""),
                "status": str(getattr(help_card, "status", "") or ""),
                "answer_count": int(getattr(help_card, "answer_count", 0) or 0),
                "min_answers_required": int(getattr(help_card, "min_answers_required", 3) or 3),
            }
            for help_card in ready_without_final[:50]
        ],
        "final_card_quality_items": quality_items[:50],
        "metadata": {
            "version": "finalizer_summary_v1",
            "contract": (
                "measure help-card finalization rate and final-card minimal contract, "
                "including help_final IntentAnswer writeback and final_ready LightEvent"
            ),
        },
    }


def _final_card_quality_issues(
    *,
    help_card: Any,
    final_card: Any | None,
    intent_answers: list[Any],
    has_light_event: bool,
) -> list[str]:
    issues: list[str] = []
    if final_card is None:
        issues.append("final_card_missing")
        return issues

    payload = getattr(final_card, "payload_json", None)
    if not isinstance(payload, dict):
        payload = {}

    if not str(getattr(final_card, "title", "") or payload.get("title") or "").strip():
        issues.append("title_missing")
    if not _decision_factor_text(final_card, payload):
        issues.append("decision_factor_missing")
    if _has_forbidden_legacy_payload(payload):
        issues.append("forbidden_legacy_fields_present")
    if not _evidence_ids(payload):
        issues.append("evidence_ids_missing")
    if not intent_answers:
        issues.append("help_final_intent_answer_missing")
    if not has_light_event:
        issues.append("final_ready_light_event_missing")

    help_card_id = _record_id(help_card)
    if help_card_id and not _payload_links_help_card(payload, help_card_id):
        issues.append("help_card_link_missing")
    return issues


def _is_ready_for_finalization(help_card: Any) -> bool:
    if _final_card_id(help_card):
        return True
    status = str(getattr(help_card, "status", "") or "")
    if status == "final_ready":
        return True
    answer_count = int(getattr(help_card, "answer_count", 0) or 0)
    min_required = int(getattr(help_card, "min_answers_required", 3) or 3)
    return answer_count >= min_required


def _decision_factor_text(final_card: Any, payload: dict[str, Any]) -> str | None:
    decision_factor = payload.get("decision_factor")
    if isinstance(decision_factor, dict) and str(decision_factor.get("text") or "").strip():
        return str(decision_factor["text"])
    if isinstance(decision_factor, str) and decision_factor.strip():
        return decision_factor
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata_factor = metadata.get("decision_factor")
        if isinstance(metadata_factor, dict) and str(metadata_factor.get("text") or "").strip():
            return str(metadata_factor["text"])
        if isinstance(metadata_factor, str) and metadata_factor.strip():
            return metadata_factor
    reason = str(getattr(final_card, "reason", "") or "").strip()
    return reason or None


def _evidence_ids(payload: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    if isinstance(payload.get("evidence_ids"), list):
        candidates.extend(payload["evidence_ids"])
    provenance = payload.get("provenance")
    if isinstance(provenance, dict) and isinstance(provenance.get("evidence_ids"), list):
        candidates.extend(provenance["evidence_ids"])
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in ("evidence_answer_ids", "answer_ids", "human_answer_ids"):
            if isinstance(metadata.get(key), list):
                candidates.extend(metadata[key])
    return [str(item) for item in candidates if str(item)]


def _payload_links_help_card(payload: dict[str, Any], help_card_id: str) -> bool:
    direct = payload.get("help_card_id")
    if direct and str(direct) == help_card_id:
        return True
    for key in ("provenance", "metadata"):
        nested = payload.get(key)
        if isinstance(nested, dict) and str(nested.get("help_card_id") or nested.get("source_ref_id") or "") == help_card_id:
            return True
    return False


def _has_forbidden_legacy_payload(payload: dict[str, Any]) -> bool:
    for key in ("reasons", "bullets", "followups", "warning"):
        if key in payload and payload.get(key):
            return True
    return False


def _group_by_source_ref(intent_answers: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for intent_answer in intent_answers:
        if str(getattr(intent_answer, "source_type", "") or "") != "help_final":
            continue
        ref = str(getattr(intent_answer, "source_ref_id", "") or "")
        if not ref:
            evidence = getattr(intent_answer, "evidence_json", None)
            if isinstance(evidence, dict):
                ref = str(evidence.get("help_card_id") or "")
        if ref:
            grouped.setdefault(ref, []).append(intent_answer)
    return grouped


def _final_card_id(help_card: Any) -> str | None:
    return _record_id_from_value(getattr(help_card, "final_recommendation_card_id", None))


def _light_help_card_id(event: Any) -> str | None:
    direct = _record_id_from_value(getattr(event, "help_card_id", None))
    if direct:
        return direct
    payload = getattr(event, "payload_json", None)
    if isinstance(payload, dict) and payload.get("help_card_id"):
        return str(payload["help_card_id"])
    return None


def _record_id(record: Any) -> str | None:
    return _record_id_from_value(getattr(record, "id", None))


def _record_id_from_value(value: Any) -> str | None:
    return str(value) if value is not None else None


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


__all__ = ["finalizer_summary", "finalizer_summary_from_records"]
