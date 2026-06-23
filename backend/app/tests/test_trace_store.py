from __future__ import annotations

from app.harness.trace_store import HARNESS_TRACE_EVENT_NAMES, TraceStore


class DummyAgentRun:
    def __init__(self) -> None:
        self.output_json: dict[str, object] = {"preexisting": True}
        self.output_snapshot = None


def test_trace_store_records_complete_harness_loop_trace() -> None:
    agent_run = DummyAgentRun()
    store = TraceStore(agent_run)

    store.record_input_gate({"intent_type": "decision_request", "should_enter_loop": True})
    store.record_context_pack({"user_message": "我在大同喜晋道，吃什么"})
    store.record_reasoner_decision(
        {
            "type": "tool",
            "tool_name": "search_knowledge",
            "tool_args": {"query": "我在大同喜晋道，吃什么"},
        }
    )
    store.record_tool_call(
        {"tool_name": "search_knowledge", "tool_args": {"query": "我在大同喜晋道，吃什么"}}
    )
    store.record_tool_result(
        {"tool_name": "search_knowledge", "status": "succeeded", "data": {"hits": []}}
    )
    store.record_evaluator_result({"passed": True, "quality_score": 1.0})
    store.record_answer_gate_result({"passed": True, "issues": []})

    trace = agent_run.output_json["loop_trace"]

    assert agent_run.output_json["preexisting"] is True
    assert [event["event"] for event in trace] == list(HARNESS_TRACE_EVENT_NAMES)
    assert [event["sequence_index"] for event in trace] == list(range(len(HARNESS_TRACE_EVENT_NAMES)))
    assert all(event["payload"] == event["data"] for event in trace)
    assert trace[3]["payload"]["name"] == "search_knowledge"
    assert trace[4]["payload"]["tool_name"] == "search_knowledge"


def test_trace_store_auto_records_tool_call_before_tool_result() -> None:
    store = TraceStore()

    store.record_tool_result(
        None,
        {"tool_name": "draft_help_card", "tool_args": {"title": "韩国小众美妆求一个"}},
        {"tool_name": "draft_help_card", "status": "succeeded", "data": {"help_card_id": "h"}},
    )

    assert [event["event"] for event in store.events] == ["tool_call", "tool_result"]
    assert store.events[0]["payload"]["tool_name"] == "draft_help_card"
    assert store.events[1]["payload"]["tool_result"]["data"]["help_card_id"] == "h"
