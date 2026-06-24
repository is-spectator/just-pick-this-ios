"""File-backed eval report review helpers for the admin console."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REVIEW_ACTION_TO_EXPECTED_CAUSE = {
    "accept_seed_gap": "seed_gap",
    "mark_agent_bug": "agent_bug",
    "mark_not_issue": "not_issue",
    "needs_more_data": "needs_more_data",
}


def default_reports_root() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    reports = repo_root / "reports"
    return reports if reports.exists() else repo_root / "benchmarks" / "reports"


def resolve_reports_root(value: Any = None) -> Path:
    if value:
        return Path(str(value)).expanduser().resolve()
    return default_reports_root()


def list_eval_runs(reports_root: Path) -> list[dict[str, Any]]:
    if not reports_root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted((item for item in reports_root.iterdir() if item.is_dir()), reverse=True):
        summary = _load_json(path / "quality_report.json")
        product_summary = _load_json(path / "product_benchmark_summary.json")
        if not summary and not product_summary:
            continue
        run_id = str(product_summary.get("run_id") or path.name)
        runs.append(
            {
                "run_id": run_id,
                "name": path.name,
                "path": str(path),
                "evaluated_cases": product_summary.get("evaluated_cases")
                or summary.get("evaluated_case_count")
                or _count_jsonl(path / "results.jsonl"),
                "pass_rate": _mapping(summary.get("summary")).get("pass_rate"),
                "average_quality_score": _mapping(summary.get("summary")).get("average_quality_score"),
                "low_quality_count": _low_quality_count(path),
                "seed_candidate_count": _count_jsonl(path / "seed_candidates.jsonl"),
                "agent_fix_issue_count": _count_jsonl(path / "agent_fix_issues.jsonl"),
            }
        )
    return runs


def low_quality_cases(
    reports_root: Path,
    run_id: str,
    *,
    limit: int = 100,
    primary_cause: str | None = None,
) -> list[dict[str, Any]]:
    run_dir = _run_dir(reports_root, run_id)
    attributions = _load_jsonl(run_dir / "quality_attribution.jsonl")
    scores = _load_jsonl(run_dir / "case_quality_scores.jsonl")
    scores_by_id = {str(item.get("case_id")): item for item in scores}
    items: list[dict[str, Any]] = []
    for attribution in attributions:
        if primary_cause and attribution.get("primary_cause") != primary_cause:
            continue
        score = scores_by_id.get(str(attribution.get("case_id")), {})
        quality = _mapping(attribution.get("quality"))
        if float(quality.get("overall") or score.get("quality_score") or 1.0) >= 0.75:
            continue
        items.append(_case_summary_payload(attribution, score=score))
        if len(items) >= limit:
            break
    return items


def low_quality_queue_summary(
    reports_root: Path,
    run_id: str,
    *,
    limit: int = 50,
    low_quality_threshold: float = 0.75,
) -> dict[str, Any]:
    run_dir = _run_dir(reports_root, run_id)
    attributions = _load_jsonl(run_dir / "quality_attribution.jsonl")
    scores = {str(item.get("case_id")): item for item in _load_jsonl(run_dir / "case_quality_scores.jsonl")}
    latest_reviews = _latest_reviews_by_case(_load_jsonl(run_dir / "human_reviews.jsonl"))

    low_quality_items: list[dict[str, Any]] = []
    for attribution in attributions:
        case_id = str(attribution.get("case_id") or "")
        score = scores.get(case_id, {})
        quality = _mapping(attribution.get("quality"))
        if float(quality.get("overall") or score.get("quality_score") or 1.0) >= low_quality_threshold:
            continue
        item = _case_summary_payload(attribution, score=score)
        review = latest_reviews.get(case_id)
        item["reviewed"] = review is not None
        item["review_action"] = review.get("action") if review else None
        item["reviewer"] = review.get("reviewer") if review else None
        low_quality_items.append(item)

    total = len(low_quality_items)
    reviewed_count = sum(1 for item in low_quality_items if item["reviewed"])
    trace_available_count = sum(
        1
        for item in low_quality_items
        if _mapping(item.get("trace_replay")).get("trace_available") is True
    )
    sorted_items = sorted(
        low_quality_items,
        key=lambda item: (float(item.get("quality_score") or 1.0), str(item.get("case_id") or "")),
    )
    return {
        "run_id": run_id,
        "low_quality_threshold": low_quality_threshold,
        "low_quality_count": total,
        "reviewed_count": reviewed_count,
        "pending_review_count": max(0, total - reviewed_count),
        "processing_rate": round(reviewed_count / total, 4) if total else 0.0,
        "trace_available_count": trace_available_count,
        "trace_coverage_rate": round(trace_available_count / total, 4) if total else 0.0,
        "by_primary_cause": _count_by(low_quality_items, "primary_cause"),
        "by_review_action": _count_by(
            [item for item in low_quality_items if item.get("review_action")],
            "review_action",
        ),
        "top_cases": sorted_items[: max(1, int(limit or 1))],
        "metadata": {
            "version": "low_quality_queue_summary_v1",
            "review_file": str(run_dir / "human_reviews.jsonl"),
            "source_files": [
                "quality_attribution.jsonl",
                "case_quality_scores.jsonl",
                "human_reviews.jsonl",
            ],
        },
    }


def case_detail(reports_root: Path, run_id: str, case_id: str) -> dict[str, Any]:
    run_dir = _run_dir(reports_root, run_id)
    result = _find_jsonl(run_dir / "results.jsonl", case_id)
    attribution = _find_jsonl(run_dir / "quality_attribution.jsonl", case_id)
    score = _find_jsonl(run_dir / "case_quality_scores.jsonl", case_id)
    seed_candidate = _find_candidate(run_dir / "seed_candidates.jsonl", case_id)
    agent_issue = _find_candidate(run_dir / "agent_fix_issues.jsonl", case_id)
    if not result and not attribution and not score:
        raise FileNotFoundError(case_id)
    return {
        "run_id": run_id,
        "case_id": case_id,
        "result": result,
        "quality": attribution,
        "score": score,
        "seed_candidate": seed_candidate,
        "agent_issue": agent_issue,
        "trace_replay": _trace_replay_payload(result=result, attribution=attribution, score=score),
    }


def review_payload(
    *,
    run_id: str,
    case_id: str,
    action: str,
    reviewer: str,
    notes: str | None = None,
    labels: Sequence[str] | None = None,
    suggested_fix: Mapping[str, Any] | str | None = None,
    seed_patch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "run_id": run_id,
        "case_id": case_id,
        "action": action,
        "reviewer": reviewer,
        "notes": notes or "",
        "labels": list(labels or []),
    }
    if suggested_fix is not None:
        payload["suggested_fix"] = suggested_fix
    if seed_patch is not None:
        payload["seed_patch"] = dict(seed_patch)
    return payload


def append_case_review(reports_root: Path, run_id: str, review: Mapping[str, Any]) -> Path:
    """Append a human review event next to file-backed eval reports.

    Admin review actions are still audited in the database; the JSONL file gives
    benchmark tooling a stable, database-independent surface for evaluator-vs-
    reviewer agreement checks.
    """

    run_dir = _run_dir(reports_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "human_reviews.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(review), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def review_alignment_summary(reports_root: Path, run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(reports_root, run_id)
    attributions = {str(item.get("case_id")): item for item in _load_jsonl(run_dir / "quality_attribution.jsonl")}
    scores = {str(item.get("case_id")): item for item in _load_jsonl(run_dir / "case_quality_scores.jsonl")}
    latest_reviews = _latest_reviews_by_case(_load_jsonl(run_dir / "human_reviews.jsonl"))

    items: list[dict[str, Any]] = []
    agreements = 0
    comparable = 0
    for case_id, review in sorted(latest_reviews.items()):
        action = str(review.get("action") or "")
        expected_cause = REVIEW_ACTION_TO_EXPECTED_CAUSE.get(action, "unknown")
        predicted_cause = _predicted_cause(attributions.get(case_id), scores.get(case_id))
        comparable_item = expected_cause not in {"unknown", "needs_more_data"} and predicted_cause != "unknown"
        agreed = comparable_item and expected_cause == predicted_cause
        if comparable_item:
            comparable += 1
            if agreed:
                agreements += 1
        items.append(
            {
                "case_id": case_id,
                "review_action": action,
                "expected_cause": expected_cause,
                "predicted_cause": predicted_cause,
                "agreed": agreed,
                "comparable": comparable_item,
                "reviewer": review.get("reviewer"),
                "notes": review.get("notes") or "",
            }
        )

    total_reviews = len(latest_reviews)
    disagreements = [item for item in items if item["comparable"] and not item["agreed"]]
    return {
        "run_id": run_id,
        "review_file": str(run_dir / "human_reviews.jsonl"),
        "total_reviews": total_reviews,
        "comparable_reviews": comparable,
        "agreements": agreements,
        "disagreements": len(disagreements),
        "agreement_rate": round(agreements / comparable, 4) if comparable else 0.0,
        "target_agreement_rate": 0.75,
        "target_met": bool(comparable and agreements / comparable >= 0.75),
        "by_review_action": _count_by(items, "review_action"),
        "by_predicted_cause": _count_by(items, "predicted_cause"),
        "items": items,
        "disagreement_items": disagreements,
    }


def _case_summary_payload(attribution: Mapping[str, Any], *, score: Mapping[str, Any]) -> dict[str, Any]:
    quality = _mapping(attribution.get("quality"))
    trace_replay = _trace_replay_payload(result=None, attribution=attribution, score=score)
    return {
        "case_id": attribution.get("case_id"),
        "group": attribution.get("group"),
        "message": attribution.get("message"),
        "status": attribution.get("status") or score.get("status"),
        "quality_score": quality.get("overall") or score.get("quality_score"),
        "primary_cause": attribution.get("primary_cause"),
        "actual_kind": attribution.get("actual_kind"),
        "expected_kind": attribution.get("expected_kind"),
        "issues": attribution.get("issues") or score.get("issues") or [],
        "trace": attribution.get("trace") or {},
        "trace_replay": trace_replay,
    }


def _latest_reviews_by_case(reviews: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        case_id = str(review.get("case_id") or "").strip()
        if not case_id:
            continue
        latest[case_id] = review
    return latest


def _predicted_cause(attribution: Mapping[str, Any] | None, score: Mapping[str, Any] | None) -> str:
    attribution_map = _mapping(attribution)
    cause = _first_text(attribution_map.get("primary_cause"))
    if cause:
        return cause
    score_map = _mapping(score)
    try:
        quality_score = float(score_map.get("quality_score") or 0.0)
    except (TypeError, ValueError):
        quality_score = 0.0
    if quality_score >= 0.75 or score_map.get("status") == "passed":
        return "not_issue"
    return "unknown"


def _count_by(items: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _trace_replay_payload(
    *,
    result: Mapping[str, Any] | None,
    attribution: Mapping[str, Any] | None,
    score: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result_map = _mapping(result)
    response = _mapping(result_map.get("response"))
    response_metadata = _mapping(response.get("metadata"))
    result_trace = _mapping(result_map.get("trace"))
    attribution_map = _mapping(attribution)
    attribution_trace = _mapping(attribution_map.get("trace"))
    score_map = _mapping(score)
    score_metadata = _mapping(score_map.get("metadata"))

    trace_id = _first_text(
        result_trace.get("trace_id"),
        result_trace.get("agent_run_id"),
        result_map.get("trace_id"),
        result_map.get("agent_run_id"),
        response.get("trace_id"),
        response_metadata.get("trace_id"),
        response_metadata.get("agent_run_id"),
        attribution_trace.get("trace_id"),
        attribution_trace.get("agent_run_id"),
        score_metadata.get("trace_id"),
        score_metadata.get("agent_run_id"),
    )
    agent_run_id = _first_text(
        result_trace.get("agent_run_id"),
        result_map.get("agent_run_id"),
        response_metadata.get("agent_run_id"),
        attribution_trace.get("agent_run_id"),
        score_metadata.get("agent_run_id"),
        trace_id,
    )
    conversation_id = _first_text(
        result_trace.get("conversation_id"),
        result_map.get("conversation_id"),
        response_metadata.get("conversation_id"),
        response.get("conversation_id"),
        attribution_trace.get("conversation_id"),
        score_metadata.get("conversation_id"),
    )
    turn_id = _first_text(
        result_trace.get("turn_id"),
        result_map.get("turn_id"),
        response_metadata.get("turn_id"),
        response.get("turn_id"),
        attribution_trace.get("turn_id"),
        score_metadata.get("turn_id"),
    )
    retrieval_run_id = _first_text(
        result_trace.get("retrieval_run_id"),
        result_map.get("retrieval_run_id"),
        response_metadata.get("retrieval_run_id"),
        attribution_trace.get("retrieval_run_id"),
        score_metadata.get("retrieval_run_id"),
    )
    runtime_path = _first_text(
        result_trace.get("runtime_path"),
        result_map.get("runtime_path"),
        response_metadata.get("runtime_path"),
        attribution_trace.get("runtime_path"),
        score_metadata.get("runtime_path"),
    )
    trace_key = agent_run_id or trace_id
    return {
        "trace_available": bool(trace_key),
        "trace_id": trace_id,
        "agent_run_id": agent_run_id,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "retrieval_run_id": retrieval_run_id,
        "runtime_path": runtime_path,
        "admin_trace_api_path": f"/admin/api/traces/{trace_key}" if trace_key else None,
        "admin_session_api_path": f"/admin/api/sessions/{conversation_id}" if conversation_id else None,
        "loop_trace_expected": bool(trace_key),
    }


def _run_dir(reports_root: Path, run_id: str) -> Path:
    direct = reports_root / run_id
    if direct.exists():
        return direct
    paths = reports_root.iterdir() if reports_root.exists() else []
    for path in paths:
        if not path.is_dir():
            continue
        summary = _load_json(path / "product_benchmark_summary.json")
        if str(summary.get("run_id") or "") == run_id:
            return path
    return direct


def _find_jsonl(path: Path, case_id: str) -> dict[str, Any] | None:
    for item in _load_jsonl(path):
        if str(item.get("case_id") or "") == case_id:
            return item
    return None


def _find_candidate(path: Path, case_id: str) -> dict[str, Any] | None:
    for item in _load_jsonl(path):
        ids = item.get("example_case_ids") or item.get("case_ids") or []
        if case_id in {str(value) for value in ids}:
            return item
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _count_jsonl(path: Path) -> int:
    return len(_load_jsonl(path))


def _low_quality_count(path: Path) -> int:
    attributions = _load_jsonl(path / "quality_attribution.jsonl")
    return sum(
        1
        for item in attributions
        if float(_mapping(item.get("quality")).get("overall") or 1.0) < 0.75
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
