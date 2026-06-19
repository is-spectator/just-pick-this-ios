from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ability.schemas import AbilityContext
from app.ability.tools.intent_answers import adapt_save_intent_answer_input
from app.agent.pipi_finalize_graph import PipiFinalizeGraph, PipiFinalizeGraphState


class StaticRetriever:
    def retrieve(self, query: str, *, limit: int = 5) -> Mapping[str, Any]:
        del query, limit
        return {
            "id": "retrieval:test-finalize",
            "query": "help answers",
            "hits": [
                {
                    "source_id": "hit:intent-answer",
                    "title": "retrieval title should not win",
                    "score": 0.91,
                    "payload": {
                        "title": "皮皮合成的最终卡",
                        "decision_factor": "综合三句真人证据后，圣水比明洞更适合这次小众逛街。",
                        "place_key": "korea-seongsu",
                        "item_key": "shopping-street",
                    },
                }
            ],
            "metadata": {"provider": "test"},
        }


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def invoke_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
    ) -> Mapping[str, Any]:
        del state
        args = dict(arguments)
        self.calls.append((name, args))
        if name == "finalize_help_card":
            return {"status": "ready", "help_card_id": args["help_card_id"]}
        if name == "create_recommendation_card":
            return {"id": "card-final", "card_id": "card-final", "status": "persisted"}
        if name == "save_intent_answer":
            metadata = dict(args.get("metadata") or {})
            return {
                "id": "intent-final",
                "status": "persisted",
                "source_type": metadata.get("source_type"),
                "source_ref_id": metadata.get("source_ref_id"),
                "confidence": metadata.get("confidence"),
            }
        if name == "light_user":
            return {"id": "light-final", "status": "persisted", "type": "final_ready"}
        raise AssertionError(f"unexpected tool: {name}")


def test_finalize_graph_records_standard_tool_chain_and_help_final_metadata() -> None:
    tools = RecordingTools()
    state = PipiFinalizeGraph(retriever=StaticRetriever(), tools=tools).invoke(
        {
            "help_card_id": "help-1",
            "question_id": "question-1",
            "conversation_id": "conversation-1",
            "user_id": "owner-1",
            "help_card": {
                "id": "help-1",
                "question_id": "question-1",
                "conversation_id": "conversation-1",
                "user_id": "owner-1",
                "title": "韩国小众逛街求一个",
                "context_text": "不想去明洞",
                "answer_count": 3,
                "min_answers_required": 3,
                "status": "collecting",
            },
            "help_answers": [
                {"id": "answer-1", "raw_text": "直接用这句当标题"},
                {"id": "answer-2", "raw_text": "圣水小店更密"},
                {"id": "answer-3", "raw_text": "预算不高也能逛"},
            ],
        }
    )

    assert state["status"] == "final_ready"
    assert [name for name, _ in tools.calls] == [
        "finalize_help_card",
        "create_recommendation_card",
        "save_intent_answer",
        "light_user",
    ]

    create_args = tools.calls[1][1]
    assert create_args["title"] == "皮皮合成的最终卡"
    assert create_args["title"] != "直接用这句当标题"

    save_args = tools.calls[2][1]
    save_metadata = save_args["metadata"]
    assert save_metadata["source_type"] == "help_final"
    assert save_metadata["source_ref_id"] == "help-1"
    assert save_metadata["confidence"] == 0.86
    assert save_metadata["human_evidence_only"] is True
    assert save_metadata["raw_text_role"] == "human_evidence"
    assert save_metadata["recommendation_card_id"] == "card-final"
    assert save_metadata["evidence_answer_ids"] == ["answer-1", "answer-2", "answer-3"]
    assert save_metadata["retrieval_hit_ids"] == ["hit:intent-answer"]


def test_finalize_graph_waits_for_min_required_before_tools() -> None:
    tools = RecordingTools()
    state = PipiFinalizeGraph(retriever=StaticRetriever(), tools=tools).invoke(
        {
            "help_card_id": "help-2",
            "help_card": {
                "id": "help-2",
                "answer_count": 2,
                "min_answers_required": 3,
                "status": "collecting",
            },
            "help_answers": [
                {"id": "answer-1", "raw_text": "圣水"},
                {"id": "answer-2", "raw_text": "别去明洞"},
            ],
        }
    )

    assert state["status"] == "needs_more_answers"
    assert tools.calls == []


def test_save_intent_answer_adapter_canonicalizes_help_final_metadata() -> None:
    payload = adapt_save_intent_answer_input(
        {
            "help_card_id": "help-3",
            "answer_text": "最终选择圣水。",
            "recommendation_card_id": "card-3",
            "decision_factor": "真人证据都指向圣水。",
            "confidence": 0.91,
            "evidence_answer_ids": ["answer-1"],
        },
        AbilityContext(metadata={"question_id": "question-3"}),
    )

    metadata = payload["metadata"]
    assert metadata["source_type"] == "help_final"
    assert metadata["source_ref_id"] == "help-3"
    assert metadata["recommendation_card_id"] == "card-3"
    assert metadata["confidence"] == 0.91
    assert payload["question_id"] == "question-3"
