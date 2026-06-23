from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import AdminAuditLog
from app.services.seed_patch_workflow import seed_workflow_summary


class _ScalarRows:
    def __init__(self, rows: list[AdminAuditLog]) -> None:
        self._rows = rows

    def all(self) -> list[AdminAuditLog]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[AdminAuditLog]) -> None:
        self._rows = rows

    def scalars(self, _statement: Any) -> _ScalarRows:
        return _ScalarRows(self._rows)


def _write_seed_candidates(root: Path) -> Path:
    run_dir = root / "run-1"
    run_dir.mkdir()
    candidate = {
        "candidate_id": "seed_candidate_000",
        "intent_key": "food.in_area.restaurant.chaoyang.hotdry",
        "priority": "high",
        "priority_score": 92,
        "example_case_ids": ["seed-gap-case"],
        "source_cases": [{"case_id": "seed-gap-case"}],
    }
    (run_dir / "seed_candidates.jsonl").write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "product_benchmark_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "finished_at": "2026-06-24T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def _audit(
    *,
    action: str,
    target_record_id: str | None,
    after_json: dict[str, Any],
    created_at: str,
) -> AdminAuditLog:
    return AdminAuditLog(
        admin_actor="ops",
        action=action,
        target_table="eval_run_cases" if action == "review_eval_case" else "intent_answers",
        target_record_id=target_record_id,
        request_json={},
        after_json=after_json,
        created_at=datetime.fromisoformat(created_at).astimezone(timezone.utc),
    )


def test_seed_workflow_summary_counts_review_and_draft_without_db(tmp_path: Path) -> None:
    _write_seed_candidates(tmp_path)
    review = _audit(
        action="review_eval_case",
        target_record_id="run-1:seed-gap-case",
        after_json={"action": "accept_seed_gap"},
        created_at="2026-06-24T12:00:00+00:00",
    )
    draft = _audit(
        action="create_seed_intent_answer_draft",
        target_record_id="intent-answer-id",
        after_json={"source_ref_id": "run-1:seed-gap-case"},
        created_at="2026-06-25T00:00:00+00:00",
    )

    summary = seed_workflow_summary(
        _FakeSession([review, draft]),  # type: ignore[arg-type]
        reports_root=tmp_path,
        run_id="run-1",
        top_limit=1,
    )

    assert summary["top_candidate_count"] == 1
    assert summary["processed_count"] == 1
    assert summary["reviewed_count"] == 1
    assert summary["accepted_seed_gap_count"] == 1
    assert summary["intent_answer_draft_count"] == 1
    assert summary["processing_rate"] == 1
    assert summary["intent_answer_draft_rate"] == 1
    assert summary["processing_rate_target_met"] is True
    assert summary["average_processing_hours"] == 12
    assert summary["processing_time_target_met"] is True
    assert summary["items"][0]["case_ids"] == ["seed-gap-case"]


def test_seed_workflow_summary_exposes_unprocessed_candidates(tmp_path: Path) -> None:
    _write_seed_candidates(tmp_path)

    summary = seed_workflow_summary(
        _FakeSession([]),  # type: ignore[arg-type]
        reports_root=tmp_path,
        run_id="run-1",
        top_limit=1,
    )

    assert summary["top_candidate_count"] == 1
    assert summary["processed_count"] == 0
    assert summary["processing_rate"] == 0
    assert summary["processing_rate_target_met"] is False
    assert summary["average_processing_hours"] is None
    assert summary["items"][0]["processed"] is False
