from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ability.schemas import (
    AbilityContext,
    AbilityPostconditionError,
    AbilityPreconditionError,
    AbilityTool,
)
from app.ability.tools._common import maybe_await, maybe_override, stable_stub_id
from app.schemas.tools import CreateRecommendationCardInput, RecommendationCardOutput

FORBIDDEN_RECOMMENDATION_INPUT_FIELDS = frozenset({"reasons", "bullets", "followups"})


async def run_create_recommendation_card(
    context: AbilityContext,
    input_data: CreateRecommendationCardInput,
) -> RecommendationCardOutput:
    handled, output = await maybe_override(context, "create_recommendation_card", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.recommendation import create_recommendation_card

        return await create_recommendation_card(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    question_id = input_data.question_id or str(context.metadata.get("question_id") or "")
    user_id = input_data.user_id or str(context.metadata.get("user_id") or "")
    image_status = "attached" if input_data.image_asset_id else "missing"
    return RecommendationCardOutput(
        card_id=stable_stub_id(
            "recommendation_card",
            input_data.question_id,
            input_data.help_card_id,
            input_data.item.title,
        ),
        question_id=question_id,
        user_id=user_id,
        item=input_data.item,
        decision_factor=input_data.decision_factor,
        image_asset_id=input_data.image_asset_id,
        image_required=input_data.image_required,
        image_status=image_status,
        evidence_ids=input_data.evidence_ids,
        confidence=input_data.confidence,
        status=input_data.status,
    )


def adapt_recommendation_card_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    forbidden_fields = sorted(FORBIDDEN_RECOMMENDATION_INPUT_FIELDS & normalized.keys())
    if forbidden_fields:
        raise AbilityPreconditionError(
            "create_recommendation_card forbids display-only fields: "
            + ", ".join(forbidden_fields)
        )
    if "decision_factors" in normalized:
        raise AbilityPreconditionError(
            "create_recommendation_card accepts exactly one decision_factor."
        )
    if isinstance(normalized.get("decision_factor"), list | tuple):
        raise AbilityPreconditionError(
            "create_recommendation_card accepts exactly one decision_factor."
        )

    retrieval_hit_ids = _string_list(normalized.pop("retrieval_hit_ids", None))
    evidence_answer_ids = _string_list(normalized.pop("evidence_answer_ids", None))
    if "evidence_ids" not in normalized:
        normalized["evidence_ids"] = [*retrieval_hit_ids, *evidence_answer_ids]

    normalized.pop("conversation_id", None)
    user_turn_id = normalized.pop("user_turn_id", None)
    normalized.pop("kind", None)
    normalized.pop("place_key", None)
    normalized.pop("item_key", None)
    decision_metadata = normalized.pop("metadata", None)

    if not normalized.get("question_id"):
        normalized["question_id"] = context.metadata.get("question_id") or user_turn_id
    if not normalized.get("user_id") and context.metadata.get("user_id"):
        normalized["user_id"] = context.metadata["user_id"]
    if not normalized.get("retrieval_run_id") and context.metadata.get("retrieval_run_id"):
        normalized["retrieval_run_id"] = context.metadata["retrieval_run_id"]
    if not normalized.get("intent_answer_id") and isinstance(decision_metadata, dict):
        intent_answer_id = decision_metadata.get("intent_answer_id")
        if intent_answer_id:
            normalized["intent_answer_id"] = intent_answer_id

    hit = _first_matching_hit(context, normalized.get("evidence_ids", []))
    hit_payload = _hit_payload(hit)
    if "item" not in normalized and hit is not None:
        title = hit_payload.get("item_title") or hit_payload.get("title") or hit.get("title")
        if title:
            normalized["item"] = {
                "title": str(title),
                "subtitle": hit_payload.get("subtitle"),
                "category": hit_payload.get("category"),
            }
    if "decision_factor" not in normalized and hit is not None:
        reason = (
            hit_payload.get("decision_factor")
            or hit_payload.get("reason")
            or hit_payload.get("text")
            or hit.get("text")
        )
        if reason:
            normalized["decision_factor"] = {"text": str(reason)}
    if not normalized.get("image_asset_id") and hit is not None:
        normalized["image_asset_id"] = hit.get("image_asset_id") or hit_payload.get("image_asset_id")
    if not normalized.get("confidence") and hit is not None:
        score = hit.get("score") or hit_payload.get("confidence")
        if isinstance(score, int | float):
            normalized["confidence"] = max(0.7, min(float(score), 1.0))

    normalized.setdefault("confidence", 0.7)
    normalized.setdefault("image_required", False)
    return normalized


async def require_recommendation_evidence(
    context: AbilityContext,
    input_data: CreateRecommendationCardInput,
) -> None:
    if not input_data.evidence_ids:
        raise AbilityPreconditionError(
            "Recommendation card requires evidence_ids before it can be created."
        )


async def require_verified_non_ai_image(
    context: AbilityContext,
    input_data: CreateRecommendationCardInput,
) -> None:
    if not input_data.image_asset_id:
        return
    if context.db is not None:
        return

    verifier = context.metadata.get("image_asset_verifier")
    if verifier is not None:
        verification = await maybe_await(verifier(input_data.image_asset_id))
        if _image_verification_allows(verification, input_data.image_asset_id):
            return
        raise AbilityPreconditionError(
            "Recommendation card image_asset_id must be verified, displayable, and non-AI."
        )

    if _context_image_asset_allows(context, input_data):
        return

    verified_ids = context.metadata.get("verified_image_asset_ids")
    if isinstance(verified_ids, str):
        verified_ids = {verified_ids}
    if verified_ids is not None and input_data.image_asset_id in set(verified_ids):
        return

    raise AbilityPreconditionError(
        "Recommendation card image_asset_id must be verified, displayable, and non-AI."
    )


async def ensure_card_output_has_image(
    context: AbilityContext,
    input_data: CreateRecommendationCardInput,
    output: RecommendationCardOutput,
) -> None:
    if input_data.image_asset_id and not output.image_asset_id:
        raise AbilityPostconditionError("Recommendation card output is missing image_asset_id.")


def build_create_recommendation_card_tool() -> AbilityTool:
    return AbilityTool(
        name="create_recommendation_card",
        input_schema=CreateRecommendationCardInput,
        output_schema=RecommendationCardOutput,
        handler=run_create_recommendation_card,
        input_adapter=adapt_recommendation_card_input,
        preconditions=(require_recommendation_evidence, require_verified_non_ai_image),
        postconditions=(ensure_card_output_has_image,),
        description="Create a recommendation card only after evidence and image guardrails pass.",
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set | frozenset):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def _first_matching_hit(
    context: AbilityContext,
    evidence_ids: Any,
) -> dict[str, Any] | None:
    hits = context.metadata.get("retrieval_hits") or []
    if not isinstance(hits, list):
        return None
    candidates = {str(item) for item in _string_list(evidence_ids)}
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_id = str(hit.get("source_id") or hit.get("id") or "")
        if not candidates or hit_id in candidates:
            return hit
    return None


def _hit_payload(hit: dict[str, Any] | None) -> dict[str, Any]:
    if hit is None:
        return {}
    payload = hit.get("payload") or hit.get("metadata") or {}
    return dict(payload) if isinstance(payload, dict) else {}


def _context_image_asset_allows(
    context: AbilityContext,
    input_data: CreateRecommendationCardInput,
) -> bool:
    image_asset_id = input_data.image_asset_id
    if image_asset_id is None:
        return True

    direct_asset = context.metadata.get("image_asset")
    if _image_record_matches(direct_asset, image_asset_id):
        return _image_record_is_allowed(direct_asset)

    image_assets = context.metadata.get("image_assets")
    if isinstance(image_assets, dict):
        candidate = image_assets.get(image_asset_id)
        if _image_record_matches(candidate, image_asset_id):
            return _image_record_is_allowed(candidate)
    elif isinstance(image_assets, list):
        for candidate in image_assets:
            if _image_record_matches(candidate, image_asset_id):
                return _image_record_is_allowed(candidate)

    hit = _first_matching_hit(context, input_data.evidence_ids)
    hit_payload = _hit_payload(hit)
    hit_asset = hit_payload.get("image_asset") or (hit or {}).get("image_asset")
    if _image_record_matches(hit_asset, image_asset_id):
        return _image_record_is_allowed(hit_asset)

    merged_hit = {**(hit or {}), **hit_payload}
    if merged_hit.get("image_asset_id") == image_asset_id:
        return _image_record_is_allowed(merged_hit)
    return False


def _image_verification_allows(value: Any, image_asset_id: str) -> bool:
    if isinstance(value, bool):
        return value
    return _image_record_matches(value, image_asset_id) and _image_record_is_allowed(value)


def _image_record_matches(value: Any, image_asset_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    candidate_id = value.get("id") or value.get("image_asset_id")
    return candidate_id is None or str(candidate_id) == image_asset_id


def _image_record_is_allowed(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    verification_status = str(value.get("verification_status") or "").lower()
    verified = bool(
        value.get("verified")
        or value.get("is_verified")
        or verification_status == "verified"
    )
    displayable = bool(value.get("displayable") or value.get("is_displayable"))
    ai_risk = str(value.get("ai_generated_risk") or "").lower()
    is_ai_generated = bool(
        value.get("is_ai_generated")
        or value.get("ai_generated")
        or ai_risk in {"high", "ai", "generated"}
    )
    return verified and displayable and not is_ai_generated


__all__ = [
    "adapt_recommendation_card_input",
    "build_create_recommendation_card_tool",
    "ensure_card_output_has_image",
    "FORBIDDEN_RECOMMENDATION_INPUT_FIELDS",
    "require_recommendation_evidence",
    "require_verified_non_ai_image",
    "run_create_recommendation_card",
]
