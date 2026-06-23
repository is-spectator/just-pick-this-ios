from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.pipi_loop import PipiLoop, PipiState
from app.agent.schemas import AnswerDecision, ToolDecision, ToolResult
from app.harness.answer_gate import AnswerGate
from app.harness.evaluator import Evaluator


class TwoStepReasoner:
    def __init__(self) -> None:
        self.seen_states: list[PipiState] = []

    def next(self, state: PipiState) -> ToolDecision | AnswerDecision:
        self.seen_states.append(state)
        if not state.tool_results:
            return ToolDecision(tool_name="search_knowledge", tool_args={"query": state.user_message}, reason="search first")
        return AnswerDecision(message="别查了，就这个。")


class TimeoutAwareReasoner:
    def next(self, state: PipiState) -> ToolDecision | AnswerDecision:
        if not state.tool_results:
            return ToolDecision(tool_name="search_knowledge", tool_args={"query": state.user_message}, reason="search first")
        tool_result = state.tool_results[-1]["tool_result"]
        if tool_result.get("ok") is False:
            return AnswerDecision(message="工具超时了，我先不硬选。")
        return AnswerDecision(message="别查了，就这个。")


class FakeAbilityCenter:
    async def call(self, tool_name: str, tool_args: dict[str, Any], *, state: PipiState) -> ToolResult:
        return ToolResult(ok=True, tool_name=tool_name, data={"hits": []})


class SlowAbilityCenter:
    async def call(self, tool_name: str, tool_args: dict[str, Any], *, state: PipiState) -> ToolResult:
        await asyncio.sleep(0.2)
        return ToolResult(ok=True, tool_name=tool_name, data={"late": True})


class NoToolAbilityCenter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, tool_name: str, tool_args: dict[str, Any], *, state: PipiState) -> ToolResult:
        self.calls.append(tool_name)
        raise AssertionError(f"{tool_name} should not be called")


class ScenarioAbilityCenter:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.calls: list[str] = []

    async def call(self, tool_name: str, tool_args: dict[str, Any], *, state: PipiState) -> ToolResult:
        self.calls.append(tool_name)
        if self.scenario == "datong":
            return _datong_tool_result(tool_name)
        if self.scenario == "korea_help":
            return _korea_help_tool_result(tool_name)
        if self.scenario == "publish":
            return ToolResult(
                ok=True,
                tool_name=tool_name,
                data={
                    "help_card_id": "help-active",
                    "status": "published",
                    "ui_events": [{"type": "help_card_published", "help_card_id": "help-active"}],
                },
            )
        raise AssertionError(f"unhandled scenario: {self.scenario}")


@pytest.mark.asyncio
async def test_pipi_loop_feeds_tool_result_back_to_reasoner() -> None:
    reasoner = TwoStepReasoner()
    result = await PipiLoop(
        reasoner=reasoner,
        ability_center=FakeAbilityCenter(),
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
    ).run(PipiState(conversation_id="c", turn_id="t", user_message="我在大同吃什么"))

    assert result.finish_reason == "answer"
    assert result.iterations == 2
    assert [event["event"] for event in result.trace] == [
        "context_pack",
        "reasoner_decision",
        "tool_call",
        "tool_result",
        "evaluator_result",
        "reasoner_decision",
        "answer_gate_result",
    ]
    assert len(reasoner.seen_states) == 2
    assert reasoner.seen_states[0].tool_results == []
    assert reasoner.seen_states[1].tool_results[0]["tool_result"]["tool_name"] == "search_knowledge"


@pytest.mark.asyncio
async def test_pipi_loop_tool_timeout_returns_failed_tool_result() -> None:
    result = await PipiLoop(
        reasoner=TimeoutAwareReasoner(),
        ability_center=SlowAbilityCenter(),
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
        tool_timeout_seconds=0.01,
        max_iters=2,
    ).run(PipiState(conversation_id="c", turn_id="t", user_message="我在大同吃什么"))

    assert result.finish_reason == "answer"
    assert result.message == "工具超时了，我先不硬选。"
    tool_result = next(event for event in result.trace if event["event"] == "tool_result")
    assert tool_result["data"]["status"] == "unavailable"
    assert tool_result["data"]["data"]["timeout"] is True
    assert tool_result["data"]["data"]["timeout_seconds"] == 0.01


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["你好", "你是谁", "随便啦"])
async def test_non_task_inputs_answer_without_tools_or_cards(message: str) -> None:
    ability_center = NoToolAbilityCenter()

    result = await PipiLoop(
        ability_center=ability_center,
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
    ).run(PipiState(conversation_id="c", turn_id="t", user_message=message))

    assert result.finish_reason == "answer"
    assert result.iterations == 1
    assert result.ui_events == []
    assert result.data == {}
    assert ability_center.calls == []
    assert [event["event"] for event in result.trace] == [
        "context_pack",
        "reasoner_decision",
        "answer_gate_result",
    ]


@pytest.mark.asyncio
async def test_datong_xijindao_searches_creates_card_then_answers() -> None:
    ability_center = ScenarioAbilityCenter("datong")

    result = await PipiLoop(
        ability_center=ability_center,
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
    ).run(PipiState(conversation_id="c", turn_id="t", user_message="我在大同喜晋道，吃什么"))

    assert ability_center.calls == ["search_knowledge", "create_recommendation_card"]
    assert result.finish_reason == "answer"
    assert result.message == "别查了，就这个。"
    assert result.ui_events == [{"type": "show_recommendation_card", "card_id": "card-datong"}]
    assert result.data["recommendation_card"]["card_id"] == "card-datong"


@pytest.mark.asyncio
async def test_korea_niche_searches_drafts_help_card_then_answers() -> None:
    ability_center = ScenarioAbilityCenter("korea_help")

    result = await PipiLoop(
        ability_center=ability_center,
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
    ).run(PipiState(conversation_id="c", turn_id="t", user_message="韩国小众美妆不去明洞，求一个"))

    assert ability_center.calls == ["search_knowledge", "draft_help_card"]
    assert result.finish_reason == "answer"
    assert result.message == "这题我不硬选，先帮你求一个。"
    assert result.ui_events == [{"type": "show_help_card_draft", "help_card_id": "help-korea"}]
    assert result.data["help_card"]["help_card_id"] == "help-korea"


@pytest.mark.asyncio
async def test_publish_without_active_help_card_answers_without_tool() -> None:
    ability_center = NoToolAbilityCenter()

    result = await PipiLoop(
        ability_center=ability_center,
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
    ).run(PipiState(conversation_id="c", turn_id="t", user_message="发出去"))

    assert result.finish_reason == "answer"
    assert result.message == "现在没有可发布的求一个。"
    assert result.ui_events == []
    assert ability_center.calls == []


@pytest.mark.asyncio
async def test_publish_with_active_help_card_calls_publish_tool() -> None:
    ability_center = ScenarioAbilityCenter("publish")

    result = await PipiLoop(
        ability_center=ability_center,
        evaluator=Evaluator(),
        answer_gate=AnswerGate(),
    ).run(
        PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="发出去",
            context_pack={"active_help_card": {"id": "help-active"}},
        )
    )

    assert ability_center.calls == ["publish_help_card"]
    assert result.finish_reason == "answer"
    assert result.message == "发出去了，等懂的人来一句。"
    assert result.data["help_card"]["help_card_id"] == "help-active"


def _datong_tool_result(tool_name: str) -> ToolResult:
    if tool_name == "search_knowledge":
        hit = {
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
        return ToolResult(
            ok=True,
            tool_name="search_knowledge",
            data={
                "retrieval_run": {"id": "retrieval-datong", "hits": [hit]},
                "retrieval_hits": [hit],
                "hits": [hit],
            },
        )
    if tool_name == "create_recommendation_card":
        return ToolResult(
            ok=True,
            tool_name="create_recommendation_card",
            data={
                "card_id": "card-datong",
                "item": {"title": "刀削面 + 肉丸子", "category": "restaurant"},
                "decision_factor": {"text": "第一次来大同，地方记忆点最强。"},
                "image_asset_id": "img-datong",
                "evidence_ids": ["hit-datong"],
                "ui_events": [{"type": "show_recommendation_card", "card_id": "card-datong"}],
            },
        )
    raise AssertionError(f"unexpected Datong tool: {tool_name}")


def _korea_help_tool_result(tool_name: str) -> ToolResult:
    if tool_name == "search_knowledge":
        return ToolResult(
            ok=True,
            tool_name="search_knowledge",
            data={"retrieval_run": {"id": "retrieval-korea", "hits": []}, "hits": []},
        )
    if tool_name == "draft_help_card":
        return ToolResult(
            ok=True,
            tool_name="draft_help_card",
            data={
                "help_card_id": "help-korea",
                "title": "韩国小众美妆不去明洞，求一个",
                "context": "韩国想买小众美妆，不去明洞",
                "wants": ["小众美妆"],
                "avoids": ["明洞"],
                "ui_events": [{"type": "show_help_card_draft", "help_card_id": "help-korea"}],
            },
        )
    raise AssertionError(f"unexpected Korea help tool: {tool_name}")
