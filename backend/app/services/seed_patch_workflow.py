"""Ops workflow for turning accepted seed patches into IntentAnswer drafts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
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


def seed_workflow_summary(
    session: Session,
    *,
    reports_root: Path,
    run_id: str,
    top_limit: int = 50,
    target_processing_rate: float = 0.8,
    target_processing_hours: float = 48.0,
) -> dict[str, Any]:
    """Summarize ops handling of generated seed candidates for an eval run.

    The generator is intentionally review-only, so completion for ISS-016/029
    is measured by explicit human workflow signals rather than product answer
    activation: review actions and draft/import creation of IntentAnswer rows.
    """

    run_dir = _run_dir(reports_root, run_id)
    candidates_path = run_dir / "seed_candidates.jsonl"
    candidates = _load_jsonl(candidates_path)
    candidates = sorted(
        candidates,
        key=lambda item: (
            -float(item.get("priority_score") or 0.0),
            str(item.get("candidate_id") or item.get("intent_key") or ""),
        ),
    )
    selected = candidates[: max(int(top_limit), 0)]
    candidate_created_at = _candidate_created_at(candidates_path, run_dir)

    case_keys = sorted(
        {
            f"{run_id}:{case_id}"
            for candidate in selected
            for case_id in _candidate_case_ids(candidate)
            if case_id
        }
    )
    audits = _seed_workflow_audits(session, case_keys=case_keys)
    review_by_case: dict[str, list[AdminAuditLog]] = {}
    draft_by_case: dict[str, list[AdminAuditLog]] = {}
    import_by_case: dict[str, list[AdminAuditLog]] = {}
    for audit in audits:
        if audit.action == "review_eval_case" and audit.target_record_id:
            review_by_case.setdefault(str(audit.target_record_id), []).append(audit)
        elif audit.action == "create_seed_intent_answer_draft":
            source_ref = _source_ref_from_audit(audit)
            if source_ref:
                draft_by_case.setdefault(source_ref, []).append(audit)
        elif audit.action == "import_intent_answer_drafts":
            for source_ref in _source_refs_from_import_audit(audit):
                import_by_case.setdefault(source_ref, []).append(audit)

    items: list[dict[str, Any]] = []
    processed_count = 0
    reviewed_count = 0
    accepted_count = 0
    drafted_count = 0
    processing_hours: list[float] = []
    for candidate in selected:
        case_ids = _candidate_case_ids(candidate)
        keys = [f"{run_id}:{case_id}" for case_id in case_ids if case_id]
        reviews = [audit for key in keys for audit in review_by_case.get(key, [])]
        drafts = [audit for key in keys for audit in draft_by_case.get(key, [])]
        imports = [audit for key in keys for audit in import_by_case.get(key, [])]
        accepted_reviews = [
            audit
            for audit in reviews
            if _mapping(audit.after_json).get("action") == "accept_seed_gap"
        ]
        reviewed = bool(reviews)
        accepted = bool(accepted_reviews)
        drafted = bool(drafts or imports)
        processed = bool(reviewed or drafted)
        if reviewed:
            reviewed_count += 1
        if accepted:
            accepted_count += 1
        if drafted:
            drafted_count += 1
        if processed:
            processed_count += 1

        event_at = _first_audit_at([*reviews, *drafts, *imports])
        hours = None
        if event_at and candidate_created_at:
            hours = max(0.0, (event_at - candidate_created_at).total_seconds() / 3600.0)
            processing_hours.append(hours)
        items.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "intent_key": candidate.get("intent_key"),
                "priority": candidate.get("priority"),
                "priority_score": candidate.get("priority_score"),
                "case_ids": case_ids,
                "reviewed": reviewed,
                "accepted_seed_gap": accepted,
                "intent_answer_drafted": drafted,
                "processed": processed,
                "first_processed_at": event_at.isoformat() if event_at else None,
                "processing_hours": round(hours, 2) if hours is not None else None,
            }
        )

    total = len(selected)
    processing_rate = processed_count / total if total else 0.0
    draft_rate = drafted_count / total if total else 0.0
    avg_hours = sum(processing_hours) / len(processing_hours) if processing_hours else None
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "candidate_count": len(candidates),
        "top_limit": top_limit,
        "top_candidate_count": total,
        "reviewed_count": reviewed_count,
        "accepted_seed_gap_count": accepted_count,
        "intent_answer_draft_count": drafted_count,
        "processed_count": processed_count,
        "processing_rate": round(processing_rate, 4),
        "intent_answer_draft_rate": round(draft_rate, 4),
        "target_processing_rate": target_processing_rate,
        "processing_rate_target_met": bool(total and processing_rate >= target_processing_rate),
        "average_processing_hours": round(avg_hours, 2) if avg_hours is not None else None,
        "target_processing_hours": target_processing_hours,
        "processing_time_target_met": bool(avg_hours is not None and avg_hours <= target_processing_hours),
        "candidate_created_at": candidate_created_at.isoformat() if candidate_created_at else None,
        "items": items,
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


def _seed_workflow_audits(session: Session, *, case_keys: list[str]) -> list[AdminAuditLog]:
    if not case_keys:
        return []
    direct_actions = {"review_eval_case"}
    indirect_actions = {"create_seed_intent_answer_draft", "import_intent_answer_drafts"}
    audits = session.scalars(
        select(AdminAuditLog)
        .where(AdminAuditLog.action.in_(direct_actions | indirect_actions))
        .order_by(AdminAuditLog.created_at.asc())
    ).all()
    key_set = set(case_keys)
    filtered: list[AdminAuditLog] = []
    for audit in audits:
        if audit.action == "review_eval_case" and str(audit.target_record_id or "") in key_set:
            filtered.append(audit)
            continue
        if audit.action == "create_seed_intent_answer_draft" and _source_ref_from_audit(audit) in key_set:
            filtered.append(audit)
            continue
        if audit.action == "import_intent_answer_drafts" and (set(_source_refs_from_import_audit(audit)) & key_set):
            filtered.append(audit)
    return filtered


def _source_ref_from_audit(audit: AdminAuditLog) -> str | None:
    payload = _mapping(audit.after_json)
    value = payload.get("source_ref_id")
    return str(value) if value else None


def _source_refs_from_import_audit(audit: AdminAuditLog) -> list[str]:
    payload = _mapping(audit.after_json)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    refs: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = item.get("source_ref_id")
        if value:
            refs.append(str(value))
    return refs


def _first_audit_at(audits: list[AdminAuditLog]) -> datetime | None:
    dates = [_ensure_aware(audit.created_at) for audit in audits if audit.created_at]
    return min(dates) if dates else None


def _candidate_case_ids(candidate: Mapping[str, Any]) -> list[str]:
    raw_ids = candidate.get("example_case_ids") or candidate.get("case_ids") or []
    ids = [str(value) for value in raw_ids if str(value)]
    source_cases = candidate.get("source_cases") if isinstance(candidate.get("source_cases"), list) else []
    for item in source_cases:
        if isinstance(item, Mapping) and item.get("case_id"):
            ids.append(str(item["case_id"]))
    return list(dict.fromkeys(ids))


def _candidate_created_at(candidates_path: Path, run_dir: Path) -> datetime | None:
    summary = _load_json(run_dir / "product_benchmark_summary.json")
    for key in ("finished_at", "generated_at", "created_at", "started_at"):
        parsed = _parse_datetime(summary.get(key))
        if parsed:
            return parsed
    if candidates_path.exists():
        return datetime.fromtimestamp(candidates_path.stat().st_mtime, tz=timezone.utc)
    return None


def _run_dir(reports_root: Path, run_id: str) -> Path:
    direct = reports_root / run_id
    if direct.exists():
        return direct
    if reports_root.exists():
        for path in reports_root.iterdir():
            if not path.is_dir():
                continue
            summary = _load_json(path / "product_benchmark_summary.json")
            if str(summary.get("run_id") or "") == run_id:
                return path
    return direct


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


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value)
    try:
        return _ensure_aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "OPS_SEED_PATCH_SOURCE_TYPE",
    "create_seed_intent_answer_draft",
    "latest_accepted_seed_patch",
    "seed_workflow_summary",
    "serialize_seed_intent_answer_draft",
]
