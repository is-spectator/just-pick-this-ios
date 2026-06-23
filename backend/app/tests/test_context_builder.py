from __future__ import annotations

from app.harness.context_builder import ContextBuilder
from app.harness.input_gate import run_input_gate


def test_context_builder_keeps_context_small() -> None:
    pack = ContextBuilder().build(
        user_message="我在三里屯想吃川菜",
        allowed_tools=["search_knowledge", "draft_help_card", "draft_help_card"],
        recent_turns=[{"id": str(index)} for index in range(6)],
        strongest_evidence=[{"score": score} for score in range(8)],
    )

    assert [turn["id"] for turn in pack.recent_turns] == ["3", "4", "5"]
    assert len(pack.strongest_evidence) == 5
    assert pack.allowed_tools == ["search_knowledge", "draft_help_card"]


def test_context_builder_preserves_input_gate_result_for_trace() -> None:
    gate = run_input_gate("我在大同喜晋道，吃什么")

    pack = ContextBuilder().build(
        gate,
        conversation_id="conversation-id",
        user_turn_id="turn-id",
        user_message="我在大同喜晋道，吃什么",
    )

    assert pack.conversation_id == "conversation-id"
    assert pack.user_turn_id == "turn-id"
    assert pack.input_gate_result is not None
    assert pack.input_gate_result["intent_type"] == "decision_request"
    assert pack.should_enter_loop is True
    assert pack.should_create_question is True
    assert pack.should_retrieve is True


def test_context_builder_attaches_evidence_pack_summary() -> None:
    pack = ContextBuilder().build(
        user_message="帮我找一下北京市朝阳区最好吃的热干面",
        allowed_tools=["search_knowledge", "create_recommendation_card"],
        retrieval_summary={"id": "retrieval-1", "query": "朝阳区 热干面"},
        strongest_evidence=[
            {
                "source_id": "hit-place",
                "source_type": "local_area_poi_fallback",
                "title": "朝阳区热干面候选",
                "score": 0.86,
                "payload": {
                    "has_answer_evidence": True,
                    "has_place_evidence": True,
                    "has_taste_or_preference_evidence": True,
                    "evidence_layers": ["amap_poi", "route", "decision_factor"],
                    "decision_factor": "朝阳区附近想吃热干面，先选这家，步行约 8 分钟。",
                    "place": {"provider": "amap", "name": "朝阳区热干面候选"},
                    "action": {"type": "open_amap"},
                    "route": {"summary_text": "步行约 8 分钟"},
                },
            }
        ],
    )

    assert pack.evidence_pack is not None
    assert pack.evidence_pack["version"] == "evidence_pack_v1"
    assert pack.evidence_pack["has_place_evidence"] is True
    assert pack.retrieval_summary is not None
    assert pack.retrieval_summary["evidence_pack"]["layer_counts"]["amap_poi"] == 1
