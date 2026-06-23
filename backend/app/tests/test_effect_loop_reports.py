from __future__ import annotations

import json
from pathlib import Path

from app.eval.agent_issue_generator import generate_agent_fix_issues
from app.eval.quality_attribution import attribute_rows, summarize_attributions
from app.eval.reporting import write_quality_reports
from app.eval.seed_candidate_generator import generate_seed_candidates


def _rec_response(*, location_state: str = "in_area", target_type: str = "restaurant") -> dict[str, object]:
    return {
        "response_kind": "recommendation_card",
        "location_state": location_state,
        "data": {
            "recommendation_card": {
                "title": "三里屯川菜馆",
                "target_type": target_type,
                "item": {"title": "三里屯川菜馆", "category": "restaurant"},
                "decision_factor": {"text": "离你近，现场落座也比较稳。"},
                "image": {"id": "img-1", "verified": True, "is_ai_generated": False},
                "evidence_ids": ["hit-1"],
                "provenance": {"retrieval_run_id": "retrieval-1"},
            }
        },
        "tool_calls": [{"name": "create_recommendation_card", "status": "succeeded"}],
        "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "retrieval-1", "runtime_path": "product"},
    }


def _help_response() -> dict[str, object]:
    return {
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
        "metadata": {"agent_run_id": "agent-2", "retrieval_run_id": "retrieval-2", "runtime_path": "product"},
    }


def test_effect_loop_reports_generate_attribution_seed_and_agent_outputs(tmp_path: Path) -> None:
    cases = [
        {
            "id": "seed-gap-chaoyang-hotdry",
            "category": "area_food",
            "message": "帮我找一下北京市朝阳区最好吃的热干面",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_area",
                "target_type": "restaurant",
            },
        },
        {
            "id": "agent-bug-haidilao",
            "category": "venue_order",
            "message": "我在三里屯海底捞，两个人不太能吃辣，帮我点",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_venue",
                "target_type": "ordering_bundle",
            },
        },
    ]
    rows = [
        {"case_id": cases[0]["id"], "case": cases[0], "message": cases[0]["message"], "response": _help_response()},
        {
            "case_id": cases[1]["id"],
            "case": cases[1],
            "message": cases[1]["message"],
            "response": _rec_response(location_state="in_area", target_type="restaurant"),
            "issues": ["location_state_mismatch"],
        },
    ]

    attributions = attribute_rows(rows)
    summary = summarize_attributions(attributions)
    seed_candidates = generate_seed_candidates(rows, attributions)
    agent_issues = generate_agent_fix_issues(attributions)
    paths = write_quality_reports(rows, tmp_path, benchmark_cases=cases)

    causes = {item["case_id"]: item["primary_cause"] for item in attributions}
    assert causes["seed-gap-chaoyang-hotdry"] == "seed_gap"
    assert causes["agent-bug-haidilao"] == "agent_bug"
    assert summary["primary_cause_counts"]["seed_gap"] == 1
    assert seed_candidates
    assert seed_candidates[0]["need"] == "approved_answer"
    assert agent_issues
    assert agent_issues[0]["primary_cause"] == "agent_bug"
    assert paths["quality_attribution_jsonl"].exists()
    assert paths["seed_candidates_jsonl"].exists()
    assert paths["agent_fix_issues_json"].exists()
    quality = json.loads((tmp_path / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["effect_attribution_summary"]["total"] == 2
