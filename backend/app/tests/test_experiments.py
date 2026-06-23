from __future__ import annotations

from app.services.experiments import (
    experiment_metadata,
    merge_experiment_metadata,
    resolve_experiment_assignments,
)


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
