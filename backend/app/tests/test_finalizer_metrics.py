from __future__ import annotations

from types import SimpleNamespace

from app.services.finalizer_metrics import finalizer_summary_from_records


def _help_card(
    id: str,
    *,
    answer_count: int,
    min_answers_required: int = 3,
    status: str = "collecting",
    final_recommendation_card_id: str | None = None,
    title: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        title=title or f"help card {id}",
        status=status,
        answer_count=answer_count,
        min_answers_required=min_answers_required,
        final_recommendation_card_id=final_recommendation_card_id,
    )


def _final_card(
    id: str,
    *,
    help_card_id: str,
    payload_json: dict[str, object] | None = None,
    title: str = "皮皮合成的最终卡",
    reason: str = "三句真人证据都指向同一个选择。",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        title=title,
        reason=reason,
        payload_json=payload_json
        or {
            "decision_factor": {"text": "三个人都提到圣水更稳。"},
            "provenance": {
                "help_card_id": help_card_id,
                "evidence_ids": ["answer-1", "answer-2", "answer-3"],
            },
        },
    )


def _intent_answer(id: str, help_card_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        source_type="help_final",
        source_ref_id=help_card_id,
        evidence_json={"source_type": "help_final", "help_card_id": help_card_id},
    )


def _light_event(id: str, help_card_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        type="final_ready",
        help_card_id=help_card_id,
        payload_json={"help_card_id": help_card_id},
    )


def test_finalizer_summary_tracks_finalization_and_quality_rates() -> None:
    summary = finalizer_summary_from_records(
        help_cards=[
            _help_card("help-final", answer_count=3, final_recommendation_card_id="final-card-1"),
            _help_card("help-ready", answer_count=3),
            _help_card("help-not-ready", answer_count=1),
        ],
        final_cards=[_final_card("final-card-1", help_card_id="help-final")],
        intent_answers=[_intent_answer("intent-final", "help-final")],
        light_events=[_light_event("light-final", "help-final")],
        window_hours=24,
    )

    assert summary["counts"] == {
        "help_card_count": 3,
        "ready_help_card_count": 2,
        "finalized_help_card_count": 1,
        "ready_without_final_count": 1,
        "final_card_quality_pass_count": 1,
        "final_card_quality_fail_count": 0,
        "intent_answer_writeback_count": 1,
        "light_event_count": 1,
    }
    assert summary["rates"] == {
        "finalization_rate": 0.5,
        "help_final_quality": 1.0,
        "intent_answer_writeback_rate": 1.0,
        "light_event_rate": 1.0,
    }
    assert summary["ready_without_final_items"][0]["help_card_id"] == "help-ready"
    assert summary["final_card_quality_items"][0]["passed"] is True
    assert summary["metadata"]["version"] == "finalizer_summary_v1"


def test_finalizer_summary_marks_broken_final_card_contract() -> None:
    summary = finalizer_summary_from_records(
        help_cards=[
            _help_card("help-broken", answer_count=3, final_recommendation_card_id="final-card-broken"),
        ],
        final_cards=[
            _final_card(
                "final-card-broken",
                help_card_id="wrong-help",
                payload_json={"reasons": ["too many"], "provenance": {"evidence_ids": []}},
                title="",
                reason="",
            )
        ],
        intent_answers=[],
        light_events=[],
    )

    item = summary["final_card_quality_items"][0]
    assert item["passed"] is False
    assert item["issues"] == [
        "title_missing",
        "decision_factor_missing",
        "forbidden_legacy_fields_present",
        "evidence_ids_missing",
        "help_final_intent_answer_missing",
        "final_ready_light_event_missing",
        "help_card_link_missing",
    ]
    assert summary["rates"]["help_final_quality"] == 0.0


def test_finalizer_summary_handles_empty_denominators() -> None:
    summary = finalizer_summary_from_records(
        help_cards=[],
        final_cards=[],
        intent_answers=[],
        light_events=[],
    )

    assert summary["counts"]["help_card_count"] == 0
    assert summary["rates"]["finalization_rate"] is None
    assert summary["rates"]["help_final_quality"] is None
    assert summary["rates"]["intent_answer_writeback_rate"] is None
    assert summary["rates"]["light_event_rate"] is None
