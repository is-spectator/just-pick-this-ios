"""Generate review candidates from shadow-vs-deterministic decision diffs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any


def generate_shadow_promotion_candidates(
    shadow_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    decisions = [dict(item) for item in shadow_report.get("decisions") or [] if isinstance(item, Mapping)]
    candidates: list[dict[str, Any]] = []
    for index, decision in enumerate(_candidate_decisions(decisions)):
        candidates.append(
            {
                "candidate_id": f"shadow_candidate_{index:03d}",
                "case_id": decision.get("case_id"),
                "group": decision.get("group") or "unknown",
                "priority": _priority(decision),
                "candidate_type": _candidate_type(decision),
                "deterministic": decision.get("deterministic"),
                "shadow": decision.get("shadow"),
                "mismatch_reason": decision.get("mismatch_reason"),
                "quality_delta": float(decision.get("quality_delta") or 0),
                "unsafe": bool(decision.get("unsafe")),
                "unsafe_to_promote_reason": decision.get("unsafe_to_promote_reason"),
                "schema_valid": bool(decision.get("schema_valid")),
                "trace_id": decision.get("trace_id"),
                "autopromote": False,
                "review_required": True,
                "suggested_actions": _suggested_actions(decision),
                "source_decision": {
                    "shadow_payload": decision.get("shadow_payload"),
                    "deterministic_quality": decision.get("deterministic_quality"),
                    "shadow_predicted_quality": decision.get("shadow_predicted_quality"),
                },
            }
        )
    return candidates


def write_shadow_promotion_candidate_reports(
    shadow_report: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    candidates = generate_shadow_promotion_candidates(shadow_report)
    paths = {
        "shadow_promotion_candidates_jsonl": output / "shadow_promotion_candidates.jsonl",
        "shadow_promotion_candidates_json": output / "shadow_promotion_candidates.json",
        "shadow_promotion_candidates_markdown": output / "shadow_promotion_candidates.md",
    }
    paths["shadow_promotion_candidates_jsonl"].write_text(
        "".join(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n" for candidate in candidates),
        encoding="utf-8",
    )
    paths["shadow_promotion_candidates_json"].write_text(
        json.dumps(
            {
                **summarize_shadow_promotion_candidates(candidates),
                "items": candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["shadow_promotion_candidates_markdown"].write_text(
        render_shadow_promotion_candidates_markdown(candidates),
        encoding="utf-8",
    )
    return paths


def render_shadow_promotion_candidates_markdown(candidates: Sequence[Mapping[str, Any]]) -> str:
    summary = summarize_shadow_promotion_candidates(candidates)
    lines = [
        "# Shadow Promotion Candidates",
        "",
        "Shadow output is audit-only. Every candidate here requires human review and has `autopromote=false`.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total candidates | {summary['total']} |",
        f"| Shadow improvement candidates | {summary['shadow_improvement_candidates']} |",
        f"| Unsafe shadow count | {summary['unsafe_shadow_count']} |",
        "",
    ]
    if not candidates:
        lines.append("No shadow promotion candidates.")
        return "\n".join(lines) + "\n"
    lines += [
        "| Candidate | Priority | Case | Type | Deterministic | Shadow | Action | Trace |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in candidates:
        actions = ", ".join(str(item) for item in candidate.get("suggested_actions") or [])
        lines.append(
            f"| `{candidate.get('candidate_id')}` | `{candidate.get('priority')}` | "
            f"`{candidate.get('case_id')}` | `{candidate.get('candidate_type')}` | "
            f"`{candidate.get('deterministic')}` | `{candidate.get('shadow')}` | "
            f"{actions or '-'} | `{candidate.get('trace_id') or ''}` |"
        )
    return "\n".join(lines) + "\n"


def summarize_shadow_promotion_candidates(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidate_type_counts = Counter(str(candidate.get("candidate_type") or "unknown") for candidate in candidates)
    priority_counts = Counter(str(candidate.get("priority") or "unknown") for candidate in candidates)
    action_counts: Counter[str] = Counter()
    for candidate in candidates:
        for action in candidate.get("suggested_actions") or []:
            action_counts[str(action)] += 1
    return {
        "total": len(candidates),
        "shadow_improvement_candidates": sum(
            1 for candidate in candidates if candidate.get("candidate_type") == "possible_improvement"
        ),
        "unsafe_shadow_count": sum(1 for candidate in candidates if bool(candidate.get("unsafe"))),
        "review_required_count": sum(1 for candidate in candidates if bool(candidate.get("review_required"))),
        "autopromote_count": sum(1 for candidate in candidates if bool(candidate.get("autopromote"))),
        "candidate_type_counts": dict(sorted(candidate_type_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "suggested_action_counts": dict(sorted(action_counts.items())),
    }


def _candidate_decisions(decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for decision in decisions:
        if decision.get("mismatch") or decision.get("unsafe") or _has_shadow_error(decision):
            selected.append(dict(decision))
    return sorted(
        selected,
        key=lambda item: (
            _priority_order(_priority(item)),
            str(item.get("group") or "unknown"),
            str(item.get("case_id") or ""),
        ),
    )


def _candidate_type(decision: Mapping[str, Any]) -> str:
    if _has_shadow_error(decision):
        return "shadow_runtime_reliability"
    if decision.get("unsafe"):
        return "unsafe_shadow_review"
    if float(decision.get("quality_delta") or 0) > 0:
        return "possible_improvement"
    return "decision_mismatch_review"


def _priority(decision: Mapping[str, Any]) -> str:
    if _has_shadow_error(decision) or decision.get("unsafe"):
        return "P1"
    if float(decision.get("quality_delta") or 0) > 0:
        return "P1"
    return "P2"


def _priority_order(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


def _has_shadow_error(decision: Mapping[str, Any]) -> bool:
    return bool(decision.get("schema_error") or decision.get("provider_error") or decision.get("timeout"))


def _suggested_actions(decision: Mapping[str, Any]) -> list[str]:
    if decision.get("schema_error"):
        return ["fix_shadow_schema_prompt", "rerun_shadow_benchmark"]
    if decision.get("provider_error") or decision.get("timeout"):
        return ["inspect_provider_reliability", "keep_product_deterministic"]
    if decision.get("unsafe"):
        return ["keep_shadow_blocked", "review_safety_reason"]
    shadow = str(decision.get("shadow") or "")
    if shadow.startswith("tool:create_recommendation_card"):
        return ["review_seed_gap", "review_evidence_policy"]
    if shadow.startswith("tool:draft_help_card"):
        return ["review_clarification_or_seed_coverage", "inspect_trace"]
    return ["human_review", "inspect_trace"]


__all__ = [
    "generate_shadow_promotion_candidates",
    "render_shadow_promotion_candidates_markdown",
    "summarize_shadow_promotion_candidates",
    "write_shadow_promotion_candidate_reports",
]
