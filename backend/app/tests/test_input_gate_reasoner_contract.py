from __future__ import annotations

from typing import Any

import pytest

from app.agent.pipi_loop import PipiState
from app.agent.reasoner import DeterministicReasoner
from app.agent.schemas import AnswerDecision, ToolDecision, ToolResult
from app.harness.context_builder import ContextBuilder
from app.harness.input_gate import run_input_gate


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["你好", "这个 app 怎么用？", "随便啦"])
async def test_non_task_inputs_do_not_enter_tool_chain(message: str) -> None:
    gate = run_input_gate(message)
    decision = await DeterministicReasoner().next(
        PipiState(
            conversation_id="c",
            turn_id="t",
            user_message=message,
            allowed_tools=["search_knowledge", "draft_help_card"],
            metadata={"input_gate_result": gate.model_dump()},
        )
    )

    assert gate.intent_type in {"greeting", "app_help", "unknown"}
    assert gate.should_enter_loop is False
    assert gate.allowed_tools == []
    assert isinstance(decision, AnswerDecision)


@pytest.mark.asyncio
async def test_decision_request_enters_loop_with_search_first() -> None:
    gate = run_input_gate("我在大同喜晋道，吃什么")

    decision = await DeterministicReasoner().next(
        PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="我在大同喜晋道，吃什么",
            allowed_tools=gate.allowed_tools,
            metadata={"input_gate_result": gate.model_dump()},
        )
    )

    assert gate.should_enter_loop is True
    assert gate.should_retrieve is True
    assert isinstance(decision, ToolDecision)
    assert decision.tool_name == "search_knowledge"


@pytest.mark.asyncio
async def test_publish_requires_active_help_card() -> None:
    reasoner = DeterministicReasoner()
    no_active_gate = run_input_gate("发出去")
    no_active = await reasoner.next(
        PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="发出去",
            metadata={"input_gate_result": no_active_gate.model_dump()},
        )
    )

    active_gate = run_input_gate("发出去", active_help_card_id="help-active")
    active = await reasoner.next(
        PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="发出去",
            allowed_tools=active_gate.allowed_tools,
            context_pack={"active_help_card": {"id": "help-active", "status": "draft"}},
            metadata={"input_gate_result": active_gate.model_dump()},
        )
    )

    assert isinstance(no_active, AnswerDecision)
    assert isinstance(active, ToolDecision)
    assert active.tool_name == "publish_help_card"
    assert active.tool_args["help_card_id"] == "help-active"


@pytest.mark.asyncio
async def test_update_feedback_with_active_draft_updates_help_card() -> None:
    gate = run_input_gate("预算不高，别太远，不要游客区，也想买美妆。", active_help_card_id="help-draft")

    decision = await DeterministicReasoner().next(
        PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="预算不高，别太远，不要游客区，也想买美妆。",
            allowed_tools=gate.allowed_tools,
            context_pack={"active_help_card": {"id": "help-draft", "status": "draft"}},
            metadata={"input_gate_result": gate.model_dump()},
        )
    )

    assert gate.intent_type == "update_help_card"
    assert isinstance(decision, ToolDecision)
    assert decision.tool_name == "update_help_card"
    assert decision.tool_args["help_card_id"] == "help-draft"


def test_context_builder_bounds_recent_turns_and_strongest_evidence() -> None:
    pack = ContextBuilder().build(
        user_message="我在三里屯想吃川菜",
        recent_turns=[{"id": str(index), "role": "user", "content": str(index)} for index in range(6)],
        strongest_evidence=[{"id": str(score), "score": score} for score in range(8)],
    )

    assert [turn["id"] for turn in pack.recent_turns] == ["3", "4", "5"]
    assert [hit["id"] for hit in pack.strongest_evidence] == ["7", "6", "5", "4", "3"]


@pytest.mark.asyncio
async def test_datong_reasoner_sequence_search_card_answer() -> None:
    reasoner = DeterministicReasoner()
    gate = run_input_gate("我在大同喜晋道，吃什么")
    state = PipiState(
        conversation_id="c",
        turn_id="t",
        user_message="我在大同喜晋道，吃什么",
        allowed_tools=gate.allowed_tools,
        metadata={"input_gate_result": gate.model_dump()},
    )

    search = await reasoner.next(state)
    assert isinstance(search, ToolDecision)
    assert search.tool_name == "search_knowledge"

    card = await reasoner.next(
        state.append_tool_result(search, _search_result([_datong_hit()]), {"passed": True})
    )
    assert isinstance(card, ToolDecision)
    assert card.tool_name == "create_recommendation_card"

    answer = await reasoner.next(
        state.append_tool_result(search, _search_result([_datong_hit()]), {"passed": True})
        .append_tool_result(card, _card_result(), {"passed": True})
    )
    assert isinstance(answer, AnswerDecision)
    assert answer.message == "别查了，就这个。"


@pytest.mark.asyncio
async def test_korea_reasoner_sequence_search_help_answer() -> None:
    reasoner = DeterministicReasoner()
    gate = run_input_gate("韩国小众美妆不去明洞，求一个")
    state = PipiState(
        conversation_id="c",
        turn_id="t",
        user_message="韩国小众美妆不去明洞，求一个",
        allowed_tools=gate.allowed_tools,
        metadata={"input_gate_result": gate.model_dump()},
    )

    search = await reasoner.next(state)
    assert isinstance(search, ToolDecision)
    assert search.tool_name == "search_knowledge"

    help_card = await reasoner.next(
        state.append_tool_result(search, _search_result([]), {"passed": True})
    )
    assert isinstance(help_card, ToolDecision)
    assert help_card.tool_name == "draft_help_card"

    answer = await reasoner.next(
        state.append_tool_result(search, _search_result([]), {"passed": True})
        .append_tool_result(help_card, _help_card_result(), {"passed": True})
    )
    assert isinstance(answer, AnswerDecision)
    assert answer.message == "这题我不硬选，先帮你求一个。"


@pytest.mark.asyncio
async def test_reasoner_reads_search_tool_result_on_next_turn_even_with_empty_context_pack() -> None:
    gate = run_input_gate("我在大同喜晋道，吃什么")
    search = ToolDecision(
        tool_name="search_knowledge",
        tool_args={"query": "我在大同喜晋道，吃什么"},
        reason="search first",
    )
    state = PipiState(
        conversation_id="c",
        turn_id="t",
        user_message="我在大同喜晋道，吃什么",
        allowed_tools=gate.allowed_tools,
        context_pack={"strongest_evidence": [], "retrieval_run": {"hits": []}},
        metadata={"input_gate_result": gate.model_dump()},
        tool_results=[
            {
                "decision": search.model_dump(),
                "tool_result": _search_result([_datong_hit()]).model_dump(),
                "evaluation": {"passed": True},
            }
        ],
    )

    decision = await DeterministicReasoner().next(state)

    assert isinstance(decision, ToolDecision)
    assert decision.tool_name == "create_recommendation_card"


def _search_result(hits: list[dict[str, Any]]) -> ToolResult:
    return ToolResult(
        ok=True,
        tool_name="search_knowledge",
        data={
            "retrieval_run": {"id": "retrieval-run", "hits": hits},
            "retrieval_hits": hits,
            "hits": hits,
        },
    )


def _datong_hit() -> dict[str, Any]:
    return {
        "id": "hit-datong",
        "source_id": "hit-datong",
        "score": 0.92,
        "payload": {
            "has_answer_evidence": True,
            "intent_answer_id": "intent-answer-datong",
            "has_verified_non_ai_image": True,
            "image_asset_id": "img-datong",
            "image_asset": {
                "id": "img-datong",
                "verified": True,
                "displayable": True,
                "is_ai_generated": False,
                "source_url": "https://example.com/datong-noodles",
                "source_domain": "example.com",
            },
            "item_title": "刀削面 + 肉丸子",
            "decision_factor": "第一次来大同，地方记忆点最强。",
            "target_type": "restaurant",
        },
    }


def _card_result() -> ToolResult:
    return ToolResult(
        ok=True,
        tool_name="create_recommendation_card",
        data={
            "card_id": "card-datong",
            "ui_events": [{"type": "show_recommendation_card", "card_id": "card-datong"}],
        },
    )


def _help_card_result() -> ToolResult:
    return ToolResult(
        ok=True,
        tool_name="draft_help_card",
        data={
            "help_card_id": "help-korea",
            "ui_events": [{"type": "show_help_card_draft", "help_card_id": "help-korea"}],
        },
    )
