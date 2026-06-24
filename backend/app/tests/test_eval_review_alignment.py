from __future__ import annotations

import json
from pathlib import Path

from app.services.eval_review_service import (
    append_case_review,
    card_contract_summary,
    evidence_quality_summary,
    help_card_quality_summary,
    low_quality_queue_summary,
    review_alignment_summary,
    review_payload,
    review_workflow_summary,
    routing_quality_summary,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_review_alignment_tracks_human_agreement_without_database(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "quality_attribution.jsonl",
        [
            {
                "case_id": "seed-gap-case",
                "primary_cause": "seed_gap",
                "quality": {"overall": 0.42},
            },
            {
                "case_id": "agent-bug-case",
                "primary_cause": "agent_bug",
                "quality": {"overall": 0.31},
            },
        ],
    )
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {"case_id": "seed-gap-case", "quality_score": 0.42, "status": "failed"},
            {"case_id": "agent-bug-case", "quality_score": 0.31, "status": "failed"},
        ],
    )

    append_case_review(
        tmp_path,
        "run-1",
        review_payload(
            run_id="run-1",
            case_id="seed-gap-case",
            action="accept_seed_gap",
            reviewer="human",
        ),
    )
    append_case_review(
        tmp_path,
        "run-1",
        review_payload(
            run_id="run-1",
            case_id="agent-bug-case",
            action="accept_seed_gap",
            reviewer="human",
        ),
    )

    summary = review_alignment_summary(tmp_path, "run-1")

    assert summary["total_reviews"] == 2
    assert summary["comparable_reviews"] == 2
    assert summary["agreements"] == 1
    assert summary["disagreements"] == 1
    assert summary["agreement_rate"] == 0.5
    assert summary["target_agreement_rate"] == 0.75
    assert summary["target_met"] is False
    assert summary["by_review_action"] == {"accept_seed_gap": 2}
    assert summary["by_predicted_cause"] == {"agent_bug": 1, "seed_gap": 1}
    assert summary["disagreement_items"][0]["case_id"] == "agent-bug-case"


def test_review_alignment_marks_passed_case_as_not_issue(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [{"case_id": "pass-case", "quality_score": 0.95, "status": "passed"}],
    )
    append_case_review(
        tmp_path,
        "run-2",
        review_payload(
            run_id="run-2",
            case_id="pass-case",
            action="mark_not_issue",
            reviewer="human",
        ),
    )

    summary = review_alignment_summary(tmp_path, "run-2")

    assert summary["agreement_rate"] == 1.0
    assert summary["target_met"] is True
    assert summary["items"][0]["predicted_cause"] == "not_issue"


def test_low_quality_queue_summary_tracks_cause_review_and_trace_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-3"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "quality_attribution.jsonl",
        [
            {
                "case_id": "seed-gap-case",
                "group": "area_food",
                "message": "朝阳区热干面",
                "primary_cause": "seed_gap",
                "quality": {"overall": 0.42},
                "trace": {"agent_run_id": "agent-1", "runtime_path": "product"},
            },
            {
                "case_id": "agent-bug-case",
                "group": "venue_order",
                "message": "三里屯海底捞帮我点",
                "primary_cause": "agent_bug",
                "quality": {"overall": 0.31},
                "trace": {"agent_run_id": "agent-2", "runtime_path": "product"},
            },
            {
                "case_id": "passed-case",
                "group": "smalltalk_app_help_unknown",
                "message": "你好",
                "primary_cause": "not_issue",
                "quality": {"overall": 0.96},
            },
        ],
    )
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {"case_id": "seed-gap-case", "quality_score": 0.42, "status": "failed"},
            {"case_id": "agent-bug-case", "quality_score": 0.31, "status": "failed"},
            {"case_id": "passed-case", "quality_score": 0.96, "status": "passed"},
        ],
    )
    append_case_review(
        tmp_path,
        "run-3",
        review_payload(
            run_id="run-3",
            case_id="seed-gap-case",
            action="accept_seed_gap",
            reviewer="human",
        ),
    )

    summary = low_quality_queue_summary(tmp_path, "run-3")

    assert summary["low_quality_count"] == 2
    assert summary["reviewed_count"] == 1
    assert summary["pending_review_count"] == 1
    assert summary["processing_rate"] == 0.5
    assert summary["trace_available_count"] == 2
    assert summary["trace_coverage_rate"] == 1.0
    assert summary["by_primary_cause"] == {"agent_bug": 1, "seed_gap": 1}
    assert summary["by_review_action"] == {"accept_seed_gap": 1}
    assert [item["case_id"] for item in summary["top_cases"]] == ["agent-bug-case", "seed-gap-case"]
    assert summary["top_cases"][1]["reviewed"] is True
    assert summary["top_cases"][1]["trace_replay"]["admin_trace_api_path"] == "/admin/api/traces/agent-1"


def test_card_contract_summary_tracks_single_decision_factor_and_legacy_field_violations(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-4"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {
                "case_id": "too-many-factors",
                "quality_score": 0.55,
                "status": "failed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"card_contract": 0.4},
                "issues": [
                    {"code": "recommendation_card_decision_factor_must_be_single"},
                    {"code": "recommendation_card_must_use_singular_decision_factor"},
                ],
            },
            {
                "case_id": "legacy-fields",
                "quality_score": 0.7,
                "status": "degraded",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"card_contract": 0.65},
                "issues": [
                    {"code": "recommendation_card_forbidden_bullets"},
                    {"code": "recommendation_card_forbidden_followups"},
                ],
            },
            {
                "case_id": "clean-card",
                "quality_score": 1.0,
                "status": "passed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"card_contract": 1.0},
                "issues": [],
            },
        ],
    )

    summary = card_contract_summary(tmp_path, "run-4")

    assert summary["scored_case_count"] == 3
    assert summary["average_card_contract_score"] == 0.6833
    assert summary["card_contract_issue_case_count"] == 2
    assert summary["too_many_decision_factor_count"] == 2
    assert summary["legacy_field_violation_count"] == 2
    assert summary["issue_counts"]["recommendation_card_forbidden_bullets"] == 1
    assert [item["case_id"] for item in summary["top_cases"]] == ["too-many-factors", "legacy-fields"]
    assert summary["metadata"]["contract"] == (
        "single item + single decision_factor + no reasons/bullets/followups/warning"
    )


def test_help_card_quality_summary_tracks_generic_help_card_issues(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-5"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {
                "case_id": "generic-title",
                "quality_score": 0.4,
                "status": "failed",
                "expected_kind": "help_card_draft",
                "actual_kind": "help_card_draft",
                "dimensions": {"help_card_quality": 0.3},
                "issues": [
                    {"code": "help_card_title_too_generic"},
                    {"code": "help_card_missing_context"},
                    {"code": "help_card_wants_too_generic"},
                ],
            },
            {
                "case_id": "product-rule-avoid",
                "quality_score": 0.65,
                "status": "degraded",
                "expected_kind": "help_card_draft",
                "actual_kind": "help_card_draft",
                "dimensions": {"help_card_specificity": 0.7},
                "issues": [
                    {"code": "help_card_avoids_contains_product_rule"},
                    {"code": "help_card_contains_generic_wants"},
                ],
            },
            {
                "case_id": "structured-help",
                "quality_score": 1.0,
                "status": "passed",
                "expected_kind": "help_card_draft",
                "actual_kind": "help_card_draft",
                "dimensions": {"help_card_quality": 1.0},
                "issues": [],
            },
        ],
    )

    summary = help_card_quality_summary(tmp_path, "run-5")

    assert summary["scored_case_count"] == 3
    assert summary["average_help_card_quality_score"] == 0.6667
    assert summary["help_card_issue_case_count"] == 2
    assert summary["generic_title_count"] == 1
    assert summary["thin_context_count"] == 1
    assert summary["generic_wants_count"] == 2
    assert summary["product_rule_avoids_count"] == 1
    assert summary["issue_counts"]["help_card_avoids_contains_product_rule"] == 1
    assert [item["case_id"] for item in summary["top_cases"]] == ["generic-title", "product-rule-avoid"]
    assert summary["metadata"]["contract"] == (
        "specific title + structured context + concrete wants/avoids/constraints"
    )


def test_routing_quality_summary_tracks_location_target_and_venue_priority_issues(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-6"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {
                "case_id": "haidilao-overridden",
                "quality_score": 0.35,
                "status": "failed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"routing": 0.35},
                "metadata": {
                    "category": "venue_order",
                    "message": "我在三里屯海底捞，两个人不太能吃辣，帮我点",
                },
                "issues": [
                    {"code": "venue_order_should_route_in_venue"},
                    {"code": "venue_order_should_return_ordering_bundle"},
                    {"code": "haidilao_route_overridden_by_area_restaurant"},
                ],
            },
            {
                "case_id": "area-target-type",
                "quality_score": 0.7,
                "status": "degraded",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"routing": 0.75},
                "metadata": {"category": "area_food", "message": "三里屯川菜"},
                "issues": [
                    {"code": "location_state_mismatch"},
                    {"code": "target_type_mismatch"},
                ],
            },
            {
                "case_id": "clean-route",
                "quality_score": 1.0,
                "status": "passed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"routing": 1.0},
                "metadata": {"category": "area_food"},
                "issues": [],
            },
        ],
    )

    summary = routing_quality_summary(tmp_path, "run-6")

    assert summary["scored_case_count"] == 3
    assert summary["average_routing_score"] == 0.7
    assert summary["routing_issue_case_count"] == 2
    assert summary["location_state_mismatch_count"] == 1
    assert summary["target_type_mismatch_count"] == 1
    assert summary["venue_ordering_priority_issue_count"] == 3
    assert summary["wrong_location_priority_count"] == 1
    assert summary["by_category"] == {"area_food": 1, "venue_order": 1}
    assert [item["case_id"] for item in summary["top_cases"]] == ["haidilao-overridden", "area-target-type"]
    assert summary["metadata"]["contract"] == (
        "venue+ordering before area, stable location_state and target_type"
    )


def test_review_workflow_summary_tracks_throughput_fix_and_seed_patch_counts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-7"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "quality_attribution.jsonl",
        [
            {
                "case_id": "seed-gap-case",
                "primary_cause": "seed_gap",
                "quality": {"overall": 0.42},
            },
            {
                "case_id": "agent-bug-case",
                "primary_cause": "agent_bug",
                "quality": {"overall": 0.31},
            },
            {
                "case_id": "passed-case",
                "primary_cause": "not_issue",
                "quality": {"overall": 0.96},
            },
        ],
    )
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {"case_id": "seed-gap-case", "quality_score": 0.42, "status": "failed"},
            {"case_id": "agent-bug-case", "quality_score": 0.31, "status": "failed"},
            {"case_id": "passed-case", "quality_score": 0.96, "status": "passed"},
        ],
    )
    append_case_review(
        tmp_path,
        "run-7",
        review_payload(
            run_id="run-7",
            case_id="seed-gap-case",
            action="accept_seed_gap",
            reviewer="human",
            labels=["seed", "area_food"],
            suggested_fix={"summary": "补朝阳区热干面 seed"},
            seed_patch={"intent_key": "area:北京:朝阳区:热干面"},
        ),
    )
    append_case_review(
        tmp_path,
        "run-7",
        review_payload(
            run_id="run-7",
            case_id="agent-bug-case",
            action="mark_agent_bug",
            reviewer="human",
            labels=["router"],
            suggested_fix="修 venue > area 优先级",
        ),
    )

    summary = review_workflow_summary(tmp_path, "run-7")

    assert summary["total_review_events"] == 2
    assert summary["reviewed_case_count"] == 2
    assert summary["low_quality_count"] == 2
    assert summary["reviewed_low_quality_count"] == 2
    assert summary["pending_low_quality_count"] == 0
    assert summary["low_quality_processing_rate"] == 1.0
    assert summary["suggested_fix_count"] == 2
    assert summary["seed_patch_count"] == 1
    assert summary["accepted_seed_gap_count"] == 1
    assert summary["agent_bug_count"] == 1
    assert summary["by_review_action"] == {"accept_seed_gap": 1, "mark_agent_bug": 1}
    assert summary["by_label"] == {"area_food": 1, "router": 1, "seed": 1}
    assert summary["metadata"]["contract"] == (
        "human review with suggested_fix/seed_patch and low-quality processing visibility"
    )


def test_evidence_quality_summary_tracks_missing_evidence_and_image_policy_issues(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-8"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {
                "case_id": "missing-evidence",
                "quality_score": 0.55,
                "status": "failed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"evidence_grounding": 0.45},
                "metadata": {"category": "area_food", "message": "朝阳区热干面"},
                "issues": [
                    {"code": "recommendation_card_missing_evidence_ids"},
                    {"code": "recommendation_card_image_asset_missing_source_domain"},
                ],
            },
            {
                "case_id": "bad-image",
                "quality_score": 0.7,
                "status": "degraded",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"evidence_safety": 0.7},
                "metadata": {"category": "product_decision"},
                "issues": [
                    {"code": "recommendation_card_image_asset_not_verified"},
                    {"code": "recommendation_card_image_asset_not_displayable"},
                    {"code": "recommendation_card_image_asset_ai_generated"},
                ],
            },
            {
                "case_id": "clean-evidence",
                "quality_score": 1.0,
                "status": "passed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"evidence_grounding": 1.0},
                "metadata": {"category": "area_food"},
                "issues": [],
            },
        ],
    )

    summary = evidence_quality_summary(tmp_path, "run-8")

    assert summary["scored_case_count"] == 3
    assert summary["average_evidence_grounding_score"] == 0.7167
    assert summary["evidence_issue_case_count"] == 2
    assert summary["missing_evidence_count"] == 1
    assert summary["image_not_verified_count"] == 1
    assert summary["image_not_displayable_count"] == 1
    assert summary["ai_image_count"] == 1
    assert summary["image_missing_source_domain_count"] == 1
    assert summary["by_category"] == {"area_food": 1, "product_decision": 1}
    assert [item["case_id"] for item in summary["top_cases"]] == ["missing-evidence", "bad-image"]
    assert summary["metadata"]["contract"] == (
        "recommendation cards need evidence_ids; optional images must be verified/displayable/non-AI"
    )
