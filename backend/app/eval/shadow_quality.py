"""Heuristic quality diff for shadow reasoner decisions.

The shadow path is audit-only. These scores are deliberately conservative and
must never promote a shadow decision into the product answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def score_shadow_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    deterministic = str(decision.get("deterministic") or "")
    shadow = str(decision.get("shadow") or "")
    mismatch = bool(decision.get("mismatch"))

    deterministic_quality = _quality_for_label(deterministic, decision, prefix="deterministic")
    shadow_quality = _quality_for_label(shadow, decision, prefix="shadow")
    unsafe_reason = _unsafe_reason(shadow, decision)

    if unsafe_reason:
        shadow_quality = min(shadow_quality, 0.2)

    quality_delta = round(shadow_quality - deterministic_quality, 4)
    return {
        "deterministic_quality": round(deterministic_quality, 4),
        "shadow_predicted_quality": round(shadow_quality, 4),
        "quality_delta": quality_delta,
        "quality_delta_estimate": quality_delta,
        "mismatch_reason": _mismatch_reason(deterministic, shadow, mismatch),
        "should_promote_shadow": False,
        "unsafe_to_promote_reason": unsafe_reason,
        "unsafe": bool(unsafe_reason),
    }


def _quality_for_label(label: str, decision: Mapping[str, Any], *, prefix: str) -> float:
    if not label or label == "none":
        return 0.0
    if decision.get(f"{prefix}_tool_not_allowed"):
        return 0.0
    if label.startswith("tool:create_recommendation_card"):
        return 0.72
    if label.startswith("tool:draft_help_card"):
        return 0.62
    if label.startswith("tool:search_knowledge"):
        return 0.55
    if label.startswith("answer:"):
        return 0.5
    if label in {"schema_error", "provider_error", "timeout"}:
        return 0.0
    return 0.45


def _unsafe_reason(label: str, decision: Mapping[str, Any]) -> str | None:
    if decision.get("schema_error"):
        return "shadow schema invalid"
    if decision.get("provider_error"):
        return "shadow provider error"
    if decision.get("timeout"):
        return "shadow provider timeout"
    if decision.get("shadow_tool_not_allowed"):
        return "shadow tool is not in allowed_tools"
    if label.startswith("tool:create_recommendation_card") and not _has_shadow_evidence(decision):
        return "shadow selected create_recommendation_card without evidence"
    if label.startswith("answer:") and decision.get("shadow_ui_events_without_card"):
        return "shadow answer has ui_events without persisted card_id"
    return None


def _has_shadow_evidence(decision: Mapping[str, Any]) -> bool:
    shadow_payload = decision.get("shadow_payload")
    if isinstance(shadow_payload, Mapping):
        for key in ("evidence_ids", "evidence", "retrieval_run_id"):
            value = shadow_payload.get(key)
            if value:
                return True
        tool_args = shadow_payload.get("tool_args")
        if isinstance(tool_args, Mapping) and tool_args.get("evidence_ids"):
            return True
    return bool(decision.get("shadow_has_evidence"))


def _mismatch_reason(deterministic: str, shadow: str, mismatch: bool) -> str:
    if not mismatch:
        return "same_decision"
    if not deterministic or not shadow:
        return "missing_decision"
    det_kind, _, det_name = deterministic.partition(":")
    shadow_kind, _, shadow_name = shadow.partition(":")
    if det_kind != shadow_kind:
        return "type_diff"
    if det_name != shadow_name:
        return "tool_name_diff" if det_kind == "tool" else "answer_diff"
    return "payload_diff"


__all__ = ["score_shadow_decision"]
