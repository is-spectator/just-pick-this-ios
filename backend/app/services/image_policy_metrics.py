"""Metrics for recommendation-card image policy compliance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImageAsset, RecommendationCard


def image_policy_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    cards = session.scalars(
        select(RecommendationCard)
        .where(RecommendationCard.created_at >= start)
        .order_by(RecommendationCard.created_at.asc())
    ).all()
    image_ids = {_card_image_asset_id(card) for card in cards if _card_image_asset_id(card)}
    images = (
        session.scalars(select(ImageAsset).where(ImageAsset.id.in_(image_ids))).all()
        if image_ids
        else []
    )
    return image_policy_summary_from_records(cards=cards, images=images, window_start=start, window_hours=since_hours)


def image_policy_summary_from_records(
    *,
    cards: list[Any],
    images: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    image_by_id = {_record_id(image): image for image in images if _record_id(image)}
    total = len(cards)
    attached_count = 0
    trusted_count = 0
    bad_count = 0
    missing_count = 0
    no_image_with_evidence_count = 0
    bad_items: list[dict[str, Any]] = []

    for card in cards:
        image = _image_for_card(card, image_by_id)
        if image is None:
            missing_count += 1
            if _card_evidence_ids(card):
                no_image_with_evidence_count += 1
            continue
        attached_count += 1
        issues = _image_policy_issues(image)
        if issues:
            bad_count += 1
            bad_items.append(
                {
                    "card_id": _record_id(card),
                    "image_id": _record_id(image) or _payload_value(image, "id"),
                    "issues": issues,
                    "source_domain": _payload_value(image, "source_domain"),
                }
            )
        else:
            trusted_count += 1

    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "counts": {
            "recommendation_card_count": total,
            "image_attached_card_count": attached_count,
            "trusted_image_card_count": trusted_count,
            "bad_image_card_count": bad_count,
            "missing_image_card_count": missing_count,
            "no_image_with_evidence_count": no_image_with_evidence_count,
        },
        "rates": {
            "image_attach_rate": _rate(attached_count, total),
            "trusted_image_rate": _rate(trusted_count, attached_count),
            "bad_image_rate": _rate(bad_count, attached_count),
            "no_image_with_evidence_rate": _rate(no_image_with_evidence_count, missing_count),
        },
        "bad_image_items": bad_items[:50],
        "metadata": {
            "version": "image_policy_summary_v1",
            "contract": "images are optional; attached images must be verified/displayable/non-AI with source_url/source_domain",
        },
    }


def _image_for_card(card: Any, image_by_id: dict[str | None, Any]) -> Any | None:
    image = getattr(card, "image_asset", None)
    if image is not None:
        return image
    image_id = _card_image_asset_id(card)
    if image_id:
        return image_by_id.get(image_id)
    payload = getattr(card, "payload_json", None)
    if isinstance(payload, dict) and isinstance(payload.get("image"), dict):
        return payload["image"]
    return None


def _image_policy_issues(image: Any) -> list[str]:
    issues: list[str] = []
    if not _truthy(_payload_value(image, "verified")) and _payload_value(image, "verification_status") != "verified":
        issues.append("image_not_verified")
    if _payload_value(image, "displayable") is not True:
        issues.append("image_not_displayable")
    if _truthy(_payload_value(image, "is_ai_generated")):
        issues.append("image_ai_generated")
    if not _payload_value(image, "source_url"):
        issues.append("image_missing_source_url")
    if not _payload_value(image, "source_domain"):
        issues.append("image_missing_source_domain")
    return issues


def _card_evidence_ids(card: Any) -> list[str]:
    payload = getattr(card, "payload_json", None)
    if not isinstance(payload, dict):
        return []
    evidence_ids = payload.get("evidence_ids")
    if isinstance(evidence_ids, list):
        return [str(item) for item in evidence_ids if str(item)]
    provenance = payload.get("provenance")
    if isinstance(provenance, dict) and isinstance(provenance.get("evidence_ids"), list):
        return [str(item) for item in provenance["evidence_ids"] if str(item)]
    return []


def _card_image_asset_id(card: Any) -> str | None:
    value = getattr(card, "image_asset_id", None)
    return str(value) if value is not None else None


def _record_id(record: Any) -> str | None:
    value = _payload_value(record, "id")
    return str(value) if value is not None else None


def _payload_value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _truthy(value: Any) -> bool:
    return bool(value) is True


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


__all__ = ["image_policy_summary", "image_policy_summary_from_records"]
