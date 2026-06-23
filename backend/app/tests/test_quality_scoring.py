from __future__ import annotations

import json

from app.eval.quality_scoring import score_case_result
from app.eval.reporting import write_quality_reports


def test_quality_report_can_be_generated(tmp_path) -> None:
    rows = [
        {
            "case": {
                "id": "datong-card",
                "category": "restaurant",
                "message": "我在大同喜晋道，吃什么",
                "expected": {"response_kind": "recommendation_card"},
            },
            "response": {
                "response_kind": "recommendation_card",
                "data": {
                    "recommendation_card": {
                        "title": "刀削面 + 肉丸子",
                        "item": {"title": "刀削面 + 肉丸子"},
                        "decision_factor": {"text": "第一次来大同，地方记忆点最强。"},
                        "image": {
                            "id": "img-1",
                            "verified": True,
                            "displayable": True,
                            "is_ai_generated": False,
                            "source_url": "https://example.com/datong-noodles",
                            "source_domain": "example.com",
                        },
                        "evidence_ids": ["hit-1"],
                    }
                },
                "tool_calls": [{"name": "create_recommendation_card", "status": "succeeded"}],
                "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "retrieval-1"},
            },
        }
    ]

    paths = write_quality_reports(rows, tmp_path, benchmark_cases=[rows[0]["case"]])

    assert (tmp_path / "quality_report.json") == paths["quality_json"]
    assert (tmp_path / "quality_report.md") == paths["quality_markdown"]
    assert (tmp_path / "case_quality_scores.jsonl") == paths["case_scores_jsonl"]
    report = json.loads((tmp_path / "quality_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    assert "datong-card" in (tmp_path / "quality_report.md").read_text(encoding="utf-8")


def test_recommendation_card_without_image_is_not_rejected_by_default() -> None:
    score = score_case_result(
        {
            "case": {
                "id": "no-image-card",
                "expected": {"response_kind": "recommendation_card"},
            },
            "response": {
                "response_kind": "recommendation_card",
                "data": {
                    "recommendation_card": {
                        "title": "朝阳区热干面",
                        "item": {"title": "朝阳区热干面"},
                        "decision_factor": {"text": "朝阳区想吃热干面，先按明确证据选这一家。"},
                        "evidence_ids": ["hit-1"],
                    }
                },
                "tool_calls": [{"name": "create_recommendation_card", "status": "succeeded"}],
                "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "retrieval-1"},
            },
        }
    )

    issue_codes = {issue.code for issue in score.issues}
    assert "recommendation_card_missing_trusted_image_or_place" not in issue_codes
    assert score.passed is True


def test_recommendation_card_image_without_source_is_not_trusted() -> None:
    score = score_case_result(
        {
            "case": {
                "id": "bad-image-card",
                "expected": {"response_kind": "recommendation_card"},
            },
            "response": {
                "response_kind": "recommendation_card",
                "data": {
                    "recommendation_card": {
                        "title": "朝阳区热干面",
                        "item": {"title": "朝阳区热干面"},
                        "decision_factor": {"text": "朝阳区想吃热干面，先按明确证据选这一家。"},
                        "evidence_ids": ["hit-1"],
                        "image": {
                            "id": "img-no-source",
                            "verified": True,
                            "displayable": True,
                            "is_ai_generated": False,
                        },
                    }
                },
                "tool_calls": [{"name": "create_recommendation_card", "status": "succeeded"}],
                "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "retrieval-1"},
            },
        }
    )

    issue_codes = {issue.code for issue in score.issues}
    assert "recommendation_card_image_asset_missing_source_url" in issue_codes
    assert "recommendation_card_image_asset_missing_source_domain" in issue_codes
