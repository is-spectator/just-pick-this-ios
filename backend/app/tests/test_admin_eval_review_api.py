from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.eval.reporting import write_quality_reports
from app.main import create_app
from app.models import AdminAuditLog, IntentAnswer
from app.services.intent_answer_import import ADMIN_INTENT_ANSWER_IMPORT_SOURCE_TYPE
from app.services.runtime import session_scope


ADMIN_TOKEN = "unit-admin-token"


@pytest.fixture
def eval_admin_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.eval_reports_root = tmp_path
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    try:
        yield client, tmp_path
    finally:
        anyio.run(client.aclose)
        get_settings.cache_clear()


def _headers() -> dict[str, str]:
    return {"authorization": f"Bearer {ADMIN_TOKEN}", "x-admin-actor": "eval-reviewer"}


def _write_report(root: Path) -> None:
    run_dir = root / "run-1"
    cases = [
        {
            "id": "seed-gap-case",
            "category": "area_food",
            "message": "帮我找一下北京市朝阳区最好吃的热干面",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_area",
                "target_type": "restaurant",
            },
        }
    ]
    response = {
        "response_kind": "help_card_draft",
        "location_state": "in_area",
        "data": {
            "help_card": {
                "title": "朝阳区热干面，求一个",
                "context": {"area": "朝阳区", "food_item": "热干面"},
                "wants": ["热干面、适合现场去"],
                "avoids": ["纯榜单推荐"],
            }
        },
        "tool_calls": [{"name": "draft_help_card", "status": "succeeded"}],
        "metadata": {"agent_run_id": "agent-review", "retrieval_run_id": "retrieval-review", "runtime_path": "product"},
    }
    rows = [
        {
            "run_id": "run-1",
            "case_id": "seed-gap-case",
            "case": cases[0],
            "message": cases[0]["message"],
            "input": cases[0]["message"],
            "response": response,
            "actual": {"response_kind": "help_card_draft", "location_state": "in_area", "target_type": "none"},
            "trace": {"agent_run_id": "agent-review", "runtime_path": "product"},
            "latency_ms": 100,
            "status": "passed",
            "status_code": 200,
        }
    ]
    write_quality_reports(rows, run_dir, benchmark_cases=cases)
    (run_dir / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    (run_dir / "product_benchmark_summary.json").write_text(
        json.dumps({"run_id": "run-1", "evaluated_cases": 1}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_admin_eval_run_review_api_reads_reports_and_writes_audit(eval_admin_client: Any) -> None:
    client, root = eval_admin_client
    _write_report(root)

    runs = await client.get("/admin/api/eval-runs", headers=_headers())
    assert runs.status_code == 200
    assert runs.json()["items"][0]["run_id"] == "run-1"

    low_quality = await client.get("/admin/api/eval-runs/run-1/low-quality-cases", headers=_headers())
    assert low_quality.status_code == 200
    assert low_quality.json()["items"][0]["case_id"] == "seed-gap-case"
    assert low_quality.json()["items"][0]["primary_cause"] == "seed_gap"

    queue_summary = await client.get("/admin/api/eval-runs/run-1/low-quality-summary", headers=_headers())
    assert queue_summary.status_code == 200, queue_summary.text
    queue_body = queue_summary.json()
    assert queue_body["low_quality_count"] == 1
    assert queue_body["pending_review_count"] == 1
    assert queue_body["by_primary_cause"] == {"seed_gap": 1}
    assert queue_body["top_cases"][0]["trace_replay"]["admin_trace_api_path"] == "/admin/api/traces/agent-review"

    card_contract = await client.get("/admin/api/eval-runs/run-1/card-contract-summary", headers=_headers())
    assert card_contract.status_code == 200, card_contract.text
    card_body = card_contract.json()
    assert card_body["scored_case_count"] == 1
    assert "average_card_contract_score" in card_body
    assert card_body["metadata"]["contract"].startswith("single item")

    help_quality = await client.get("/admin/api/eval-runs/run-1/help-card-quality-summary", headers=_headers())
    assert help_quality.status_code == 200, help_quality.text
    help_body = help_quality.json()
    assert help_body["scored_case_count"] == 1
    assert "average_help_card_quality_score" in help_body
    assert help_body["metadata"]["contract"].startswith("specific title")

    detail = await client.get("/admin/api/eval-runs/run-1/cases/seed-gap-case", headers=_headers())
    assert detail.status_code == 200
    assert detail.json()["quality"]["case_id"] == "seed-gap-case"
    assert detail.json()["seed_candidate"]

    initial_summary = await client.get(
        "/admin/api/eval-runs/run-1/seed-workflow-summary?top_limit=1",
        headers=_headers(),
    )
    assert initial_summary.status_code == 200, initial_summary.text
    initial_body = initial_summary.json()
    assert initial_body["top_candidate_count"] == 1
    assert initial_body["processed_count"] == 0
    assert initial_body["processing_rate"] == 0
    assert initial_body["processing_rate_target_met"] is False

    review = await client.post(
        "/admin/api/eval-runs/run-1/cases/seed-gap-case/review",
        headers=_headers(),
        json={
            "action": "accept_seed_gap",
            "notes": "补 approved answer",
            "labels": ["seed"],
            "suggested_fix": {
                "owner": "data",
                "summary": "补朝阳区热干面 approved answer",
            },
            "seed_patch": {
                "intent_key": "area:北京:朝阳区:热干面",
                "area": "朝阳区",
                "food_item": "热干面",
            },
        },
    )
    assert review.status_code == 200
    assert review.json()["review"]["action"] == "accept_seed_gap"
    assert review.json()["review"]["suggested_fix"]["owner"] == "data"
    assert review.json()["review"]["seed_patch"]["food_item"] == "热干面"
    review_file = root / "run-1" / "human_reviews.jsonl"
    assert review_file.exists()
    review_rows = [
        json.loads(line)
        for line in review_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert review_rows[-1]["case_id"] == "seed-gap-case"
    assert review_rows[-1]["action"] == "accept_seed_gap"

    alignment = await client.get("/admin/api/eval-runs/run-1/review-alignment", headers=_headers())
    assert alignment.status_code == 200, alignment.text
    assert alignment.json()["agreement_rate"] == 1.0
    assert alignment.json()["target_met"] is True
    assert alignment.json()["items"][0]["predicted_cause"] == "seed_gap"

    reviewed_summary = await client.get(
        "/admin/api/eval-runs/run-1/seed-workflow-summary?top_limit=1",
        headers=_headers(),
    )
    assert reviewed_summary.status_code == 200, reviewed_summary.text
    reviewed_body = reviewed_summary.json()
    assert reviewed_body["reviewed_count"] == 1
    assert reviewed_body["accepted_seed_gap_count"] == 1
    assert reviewed_body["processed_count"] == 1
    assert reviewed_body["processing_rate"] == 1
    assert reviewed_body["processing_rate_target_met"] is True
    assert reviewed_body["intent_answer_draft_count"] == 0
    assert reviewed_body["items"][0]["processed"] is True
    assert reviewed_body["items"][0]["accepted_seed_gap"] is True

    draft = await client.post(
        "/admin/api/eval-runs/run-1/cases/seed-gap-case/seed-intent-answer-draft",
        headers=_headers(),
        json={},
    )
    assert draft.status_code == 200, draft.text
    draft_body = draft.json()["intent_answer"]
    assert draft_body["intent_key"] == "area:北京:朝阳区:热干面"
    assert draft_body["source_type"] == "ops_seed_patch"
    assert draft_body["source_ref_id"] == "run-1:seed-gap-case"
    assert draft_body["is_active"] is False
    assert draft_body["constraints"]["area"] == "朝阳区"
    assert draft_body["constraints"]["food_item"] == "热干面"
    assert draft_body["evidence"]["draft"] is True
    assert draft_body["evidence"]["approved"] is False

    idempotent = await client.post(
        "/admin/api/eval-runs/run-1/cases/seed-gap-case/seed-intent-answer-draft",
        headers=_headers(),
        json={},
    )
    assert idempotent.status_code == 200, idempotent.text
    assert idempotent.json()["intent_answer"]["id"] == draft_body["id"]

    drafted_summary = await client.get(
        "/admin/api/eval-runs/run-1/seed-workflow-summary?top_limit=1",
        headers=_headers(),
    )
    assert drafted_summary.status_code == 200, drafted_summary.text
    drafted_body = drafted_summary.json()
    assert drafted_body["intent_answer_draft_count"] == 1
    assert drafted_body["intent_answer_draft_rate"] == 1
    assert drafted_body["average_processing_hours"] is not None
    assert drafted_body["average_processing_hours"] <= 48
    assert drafted_body["processing_time_target_met"] is True
    assert drafted_body["items"][0]["intent_answer_drafted"] is True

    with session_scope() as session:
        audit = session.scalar(
            select(AdminAuditLog)
            .where(AdminAuditLog.action == "review_eval_case")
            .order_by(AdminAuditLog.created_at.desc())
            .limit(1)
        )
        assert audit is not None
        assert audit.target_record_id == "run-1:seed-gap-case"
        assert audit.after_json is not None
        assert audit.after_json["suggested_fix"]["summary"] == "补朝阳区热干面 approved answer"
        assert audit.after_json["seed_patch"]["intent_key"] == "area:北京:朝阳区:热干面"
        intent_answer = session.get(IntentAnswer, uuid.UUID(draft_body["id"]))
        assert intent_answer is not None
        assert intent_answer.is_active is False
        assert intent_answer.source_type == "ops_seed_patch"

        draft_audit = session.scalar(
            select(AdminAuditLog)
            .where(AdminAuditLog.action == "create_seed_intent_answer_draft")
            .order_by(AdminAuditLog.created_at.desc())
            .limit(1)
        )
        assert draft_audit is not None
        assert draft_audit.target_table == "intent_answers"
        assert draft_audit.after_json["id"] == draft_body["id"]

    invalid = await client.post(
        "/admin/api/eval-runs/run-1/cases/seed-gap-case/review",
        headers=_headers(),
        json={"action": "accept_seed_gap", "seed_patch": "not-an-object"},
    )
    assert invalid.status_code == 422

    invalid_draft = await client.post(
        "/admin/api/eval-runs/run-1/cases/seed-gap-case/seed-intent-answer-draft",
        headers=_headers(),
        json={"seed_patch": {"area": "朝阳区"}},
    )
    assert invalid_draft.status_code == 422


@pytest.mark.anyio
async def test_admin_imports_intent_answer_drafts_idempotently(eval_admin_client: Any) -> None:
    client, _root = eval_admin_client
    payload = {
        "items": [
            {
                "intent_key": "area:北京:五道口:韩餐",
                "intent_text": "北京五道口韩餐",
                "answer_title": "五道口韩餐，就选这家",
                "answer_summary": "五道口想吃韩餐，优先选距离近、翻台稳定的一家。",
                "constraints": {"city": "北京", "area": "五道口", "cuisine": "韩餐"},
                "source_ref_id": "manual-seed-001",
                "confidence": 0.82,
                "tags": ["area_food", "seed_candidate"],
                "is_active": True,
            }
        ]
    }

    response = await client.post(
        "/admin/api/intent-answers/import-drafts",
        headers=_headers(),
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    imported = body["items"][0]
    assert imported["intent_key"] == "area:北京:五道口:韩餐"
    assert imported["source_type"] == ADMIN_INTENT_ANSWER_IMPORT_SOURCE_TYPE
    assert imported["source_ref_id"] == "manual-seed-001"
    assert imported["is_active"] is False
    assert imported["constraints"]["area"] == "五道口"
    assert imported["evidence"]["draft"] is True

    second = await client.post(
        "/admin/api/intent-answers/import-drafts",
        headers=_headers(),
        json={
            "items": [
                {
                    **payload["items"][0],
                    "answer_summary": "五道口想吃韩餐，更新为更适合现场直接去的一家。",
                }
            ]
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["id"] == imported["id"]
    assert "更新为更适合现场" in second.json()["items"][0]["answer_summary"]

    with session_scope() as session:
        answer = session.get(IntentAnswer, uuid.UUID(imported["id"]))
        assert answer is not None
        assert answer.is_active is False
        assert answer.answer_summary == "五道口想吃韩餐，更新为更适合现场直接去的一家。"
        assert answer.success_count == 0
        assert answer.rejection_count == 0
        audit = session.scalar(
            select(AdminAuditLog)
            .where(AdminAuditLog.action == "import_intent_answer_drafts")
            .order_by(AdminAuditLog.created_at.desc())
            .limit(1)
        )
        assert audit is not None
        assert audit.target_table == "intent_answers"
        assert audit.after_json["items"][0]["id"] == imported["id"]

    invalid = await client.post(
        "/admin/api/intent-answers/import-drafts",
        headers=_headers(),
        json={"items": [{"intent_key": "area:北京:五道口:韩餐"}]},
    )
    assert invalid.status_code == 422
