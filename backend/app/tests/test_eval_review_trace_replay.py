from __future__ import annotations

import json
from pathlib import Path

from app.services.eval_review_service import case_detail, low_quality_cases


def test_eval_review_low_quality_cases_include_trace_replay(tmp_path: Path) -> None:
    run_dir = _write_trace_review_report(tmp_path)

    items = low_quality_cases(tmp_path, run_dir.name)

    assert len(items) == 1
    replay = items[0]["trace_replay"]
    assert replay["trace_available"] is True
    assert replay["agent_run_id"] == "agent-review"
    assert replay["trace_id"] == "agent-review"
    assert replay["retrieval_run_id"] == "retrieval-review"
    assert replay["runtime_path"] == "product"
    assert replay["admin_trace_api_path"] == "/admin/api/traces/agent-review"


def test_eval_review_case_detail_includes_trace_replay_from_result(tmp_path: Path) -> None:
    run_dir = _write_trace_review_report(tmp_path)

    detail = case_detail(tmp_path, run_dir.name, "seed-gap-case")

    replay = detail["trace_replay"]
    assert replay["trace_available"] is True
    assert replay["agent_run_id"] == "agent-review"
    assert replay["conversation_id"] == "conversation-review"
    assert replay["turn_id"] == "turn-review"
    assert replay["admin_trace_api_path"] == "/admin/api/traces/agent-review"
    assert replay["admin_session_api_path"] == "/admin/api/sessions/conversation-review"
    assert replay["loop_trace_expected"] is True


def _write_trace_review_report(root: Path) -> Path:
    run_dir = root / "trace-run"
    run_dir.mkdir()
    result = {
        "case_id": "seed-gap-case",
        "message": "帮我找一下北京市朝阳区最好吃的热干面",
        "response": {
            "conversation_id": "conversation-review",
            "turn_id": "turn-review",
            "response_kind": "help_card_draft",
            "metadata": {
                "agent_run_id": "agent-review",
                "retrieval_run_id": "retrieval-review",
                "runtime_path": "product",
            },
        },
        "trace": {
            "agent_run_id": "agent-review",
            "conversation_id": "conversation-review",
            "turn_id": "turn-review",
            "retrieval_run_id": "retrieval-review",
            "runtime_path": "product",
        },
    }
    attribution = {
        "case_id": "seed-gap-case",
        "group": "area_food",
        "message": result["message"],
        "status": "degraded",
        "primary_cause": "seed_gap",
        "actual_kind": "help_card_draft",
        "expected_kind": "recommendation_card",
        "quality": {"overall": 0.42},
        "issues": [{"code": "expected_recommendation_but_help_card"}],
        "trace": {
            "trace_id": "agent-review",
            "agent_run_id": "agent-review",
            "retrieval_run_id": "retrieval-review",
            "runtime_path": "product",
        },
    }
    score = {
        "case_id": "seed-gap-case",
        "quality_score": 0.42,
        "status": "degraded",
        "metadata": {"agent_run_id": "agent-review", "retrieval_run_id": "retrieval-review"},
    }
    _write_jsonl(run_dir / "results.jsonl", [result])
    _write_jsonl(run_dir / "quality_attribution.jsonl", [attribution])
    _write_jsonl(run_dir / "case_quality_scores.jsonl", [score])
    (run_dir / "quality_report.json").write_text(
        json.dumps({"summary": {"average_quality_score": 0.42}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return run_dir


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
