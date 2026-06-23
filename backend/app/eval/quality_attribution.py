"""Quality attribution for effect-loop benchmark rows."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.eval.quality_scoring import CaseQualityScore, score_case_result


PRIMARY_CAUSES = (
    "agent_bug",
    "seed_gap",
    "card_quality",
    "retrieval_gap",
    "latency",
    "unknown",
)
PrimaryCause = Literal[
    "agent_bug",
    "seed_gap",
    "card_quality",
    "retrieval_gap",
    "latency",
    "unknown",
]

EFFECT_DIMENSIONS = (
    "intent_routing",
    "answer_usefulness",
    "specificity",
    "card_contract",
    "help_card_quality",
    "evidence_grounding",
    "tone",
    "latency",
)


def attribute_row(row: Mapping[str, Any]) -> dict[str, Any]:
    score = score_case_result(row)
    return attribute_score(score, row=row)


def attribute_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [attribute_row(row) for row in rows]


def summarize_attributions(attributions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cause_counts = Counter(str(item.get("primary_cause") or "unknown") for item in attributions)
    issue_counts = Counter(
        str(issue)
        for item in attributions
        for issue in _sequence(item.get("issues"))
    )
    return {
        "total": len(attributions),
        "primary_cause_counts": dict(sorted(cause_counts.items())),
        "top_issues": [
            {"code": code, "count": count}
            for code, count in issue_counts.most_common(20)
        ],
        "average_overall": round(
            sum(float(_mapping(item.get("quality")).get("overall") or 0) for item in attributions)
            / len(attributions),
            4,
        )
        if attributions
        else 0.0,
    }


def attribute_score(
    score: CaseQualityScore,
    *,
    row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = row or {}
    issues = [issue.code for issue in score.issues]
    dimensions = _effect_dimensions(score, row=row)
    primary_cause = _primary_cause(score, issues=issues, row=row)
    return {
        "case_id": score.case_id,
        "status": score.status,
        "passed": score.passed,
        "expected_kind": score.expected_kind,
        "actual_kind": score.actual_kind,
        "primary_cause": primary_cause,
        "issues": issues,
        "quality": {
            "overall": score.quality_score,
            "dimensions": dimensions,
            "issues": issues,
            "primary_cause": primary_cause,
        },
        "trace": _trace_payload(score, row),
        "message": score.metadata.get("message") or row.get("message") or row.get("input") or "",
        "group": score.metadata.get("category") or row.get("group") or row.get("category") or "unknown",
    }


def _effect_dimensions(score: CaseQualityScore, *, row: Mapping[str, Any]) -> dict[str, float]:
    legacy = score.dimensions
    latency_value = _latency(row, score)
    latency_score = 1.0
    if latency_value is not None and latency_value > 6000:
        latency_score = 0.45
    elif latency_value is not None and latency_value > 3500:
        latency_score = 0.75
    if _has_issue(score, "latency_too_high"):
        latency_score = min(latency_score, 0.5)
    return {
        "intent_routing": min(
            legacy.get("response_kind", 1.0),
            legacy.get("routing", 1.0),
            legacy.get("tool_call", 1.0),
        ),
        "answer_usefulness": min(legacy.get("response_kind", 1.0), score.quality_score),
        "specificity": min(
            legacy.get("help_card_specificity", 1.0),
            legacy.get("card_contract", 1.0),
        ),
        "card_contract": legacy.get("card_contract", 1.0),
        "help_card_quality": legacy.get("help_card_specificity", 1.0),
        "evidence_grounding": legacy.get("evidence_safety", 1.0),
        "tone": 1.0,
        "latency": round(latency_score, 4),
    }


def _primary_cause(
    score: CaseQualityScore,
    *,
    issues: Sequence[str],
    row: Mapping[str, Any],
) -> PrimaryCause:
    issue_set = set(issues) | {str(issue) for issue in _sequence(row.get("issues"))}
    if score.expected_kind == "recommendation_card" and score.actual_kind == "help_card_draft":
        return "seed_gap"
    if issue_set & {"runtime_bypass", "response_kind_mismatch", "location_state_mismatch", "target_type_mismatch"}:
        return "agent_bug"
    if any(code.startswith("tool_call_") or code.startswith("venue_order_") for code in issue_set):
        return "agent_bug"
    if any(code.startswith("help_card_") or code.startswith("recommendation_card_") for code in issue_set):
        return "card_quality"
    if any("retrieval" in code or "evidence" in code or "image" in code for code in issue_set):
        return "retrieval_gap"
    if any("latency" in code for code in issue_set):
        return "latency"
    if score.status != "passed":
        return "agent_bug"
    return "unknown"


def _trace_payload(score: CaseQualityScore, row: Mapping[str, Any]) -> dict[str, Any]:
    row_trace = _mapping(row.get("trace"))
    return {
        "trace_id": row_trace.get("trace_id") or score.metadata.get("trace_id"),
        "agent_run_id": row_trace.get("agent_run_id") or score.metadata.get("agent_run_id"),
        "retrieval_run_id": row_trace.get("retrieval_run_id") or score.metadata.get("retrieval_run_id"),
        "runtime_path": row_trace.get("runtime_path") or _runtime_path(row),
    }


def _runtime_path(row: Mapping[str, Any]) -> str | None:
    response = _mapping(row.get("response"))
    metadata = _mapping(response.get("metadata"))
    return str(metadata.get("runtime_path")) if metadata.get("runtime_path") else None


def _latency(row: Mapping[str, Any], score: CaseQualityScore) -> float | None:
    value = row.get("latency_ms") or score.metadata.get("latency_ms")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_issue(score: CaseQualityScore, code: str) -> bool:
    return any(issue.code == code for issue in score.issues)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []
