from __future__ import annotations

from app.services.experiments import (
    experiment_metadata,
    merge_experiment_metadata,
    resolve_experiment_assignments,
)
from app.eval.experiment_lift import build_experiment_lift_report
from app.eval.reporting import write_quality_reports


def test_experiment_assignment_is_stable_for_same_user() -> None:
    first = resolve_experiment_assignments(user_id="user-1", conversation_id="conv-1")
    second = resolve_experiment_assignments(user_id="user-1", conversation_id="conv-2")

    assert first == second
    assert first[0]["experiment_id"] == "pipi_card_copy_v1"
    assert first[0]["variant_id"] in {"control", "concise_copy"}
    assert first[0]["source"] == "server_hash"
    assert "assignment_key_hash" in first[0]


def test_client_experiment_assignment_override_is_preserved() -> None:
    assignments = resolve_experiment_assignments(
        user_id="user-1",
        client_context={"experiment_assignments": {"pipi_card_copy_v1": "operator_holdout"}},
    )

    assert assignments == [
        {
            "experiment_id": "pipi_card_copy_v1",
            "variant_id": "operator_holdout",
            "source": "client",
            "version": 1,
        }
    ]


def test_experiment_metadata_and_event_merge() -> None:
    assignments = resolve_experiment_assignments(device_uid="device-1")
    metadata = experiment_metadata(assignments)

    assert metadata["assignments"] == assignments
    assert metadata["variant_ids"]["pipi_card_copy_v1"] == assignments[0]["variant_id"]

    merged = merge_experiment_metadata({"surface": "card"}, assignments)
    assert merged["surface"] == "card"
    assert merged["experiment_assignments"] == assignments
    assert merged["experiment_variant_ids"] == metadata["variant_ids"]


def test_list_assignment_normalization_preserves_assignment_hash() -> None:
    assignments = resolve_experiment_assignments(
        client_context={
            "experiment_assignments": [
                {
                    "experiment_id": "pipi_card_copy_v1",
                    "variant_id": "control",
                    "source": "server_hash",
                    "version": 1,
                    "assignment_key_hash": "abc123",
                }
            ]
        }
    )

    assert assignments[0]["assignment_key_hash"] == "abc123"


def test_experiment_lift_report_groups_quality_by_variant(tmp_path) -> None:
    rows = [
        _result_row("case-control", "control", quality_expected_kind="recommendation_card", accepted=True),
        _result_row("case-variant", "concise_copy", quality_expected_kind="recommendation_card", accepted=False),
        _result_row("case-variant-2", "concise_copy", quality_expected_kind="help_card_draft", accepted=False),
    ]

    report = build_experiment_lift_report(rows)

    assert report["summary"]["assigned_rows"] == 3
    variants = report["experiments"]["pipi_card_copy_v1"]["variants"]
    assert variants["control"]["case_count"] == 1
    assert variants["control"]["accept_rate"] == 1.0
    assert variants["concise_copy"]["case_count"] == 2

    paths = write_quality_reports(rows, tmp_path)
    assert paths["experiment_lift_markdown"].exists()
    assert paths["experiment_lift_json"].exists()
    assert "Experiment Lift Report" in paths["experiment_lift_markdown"].read_text(encoding="utf-8")


def _result_row(
    case_id: str,
    variant_id: str,
    *,
    quality_expected_kind: str,
    accepted: bool,
) -> dict:
    response_kind = quality_expected_kind
    data = {}
    ui_events = []
    tool_calls = []
    if response_kind == "recommendation_card":
        ui_events = [{"type": "show_recommendation_card", "card_id": f"card-{case_id}"}]
        tool_calls = [{"name": "create_recommendation_card", "status": "succeeded"}]
        data = {
            "recommendation_card": {
                "id": f"card-{case_id}",
                "title": "三里屯川菜，就选这家",
                "item": {"title": "三里屯川菜，就选这家"},
                "target_type": "restaurant",
                "decision_factor": {"text": "离你近，现场去不折腾。"},
                "evidence_ids": ["hit-1"],
            }
        }
    else:
        ui_events = [{"type": "show_help_card_draft", "help_card_id": f"help-{case_id}"}]
        tool_calls = [{"name": "draft_help_card", "status": "succeeded"}]
        data = {
            "help_card": {
                "id": f"help-{case_id}",
                "title": "三里屯川菜现场求一个",
                "context": {"area": "三里屯", "cuisine": "川菜"},
                "wants": ["离得近、适合现在去"],
                "avoids": ["排队太久"],
            }
        }
    return {
        "case_id": case_id,
        "expected": {
            "response_kind": quality_expected_kind,
            "location_state": "in_area",
            "target_type": "restaurant" if response_kind == "recommendation_card" else None,
        },
        "response_kind": response_kind,
        "location_state": "in_area",
        "ui_events": ui_events,
        "data": data,
        "tool_calls": tool_calls,
        "metadata": {
            "agent_run_id": f"agent-{case_id}",
            "retrieval_run_id": "retrieval-1",
            "experiments": {
                "variant_ids": {"pipi_card_copy_v1": variant_id},
            },
        },
        "accepted": accepted,
    }
