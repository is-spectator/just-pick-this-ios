from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.agent import model_adapter as model_adapter_module
from app.agent.model_adapter import DeterministicPipiModelAdapter, OpenAIPipiModelAdapter


def test_openai_adapter_keeps_publish_as_local_control_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OpenAIPipiModelAdapter(fallback=DeterministicPipiModelAdapter())

    def fail_if_model_called(self: OpenAIPipiModelAdapter, **_: object) -> dict[str, object]:
        raise AssertionError("publish_help should be classified before any OpenAI call")

    monkeypatch.setattr(OpenAIPipiModelAdapter, "_chat_json", fail_if_model_called)

    state = {
        "conversation_id": "conversation-id",
        "user_turn_id": "turn-id",
        "user_message": "发出去",
        "context": {
            "facts": {
                "latest_user_context": "我在四季民福，哪个菜最好吃",
                "has_decision_context": True,
            }
        },
        "metadata": {"active_help_card_id": "help-card-id"},
    }

    assert adapter.classify_intent("发出去") == "publish_help"
    assert adapter.classify_intent_for_state(state) == "publish_help"

    next_action, tool_call = adapter.decide_next_action({**state, "intent": "publish_help"})
    assert next_action == "call_tool"
    assert tool_call is not None
    assert tool_call["name"] == "publish_help_card"
    assert tool_call["arguments"]["help_card_id"] == "help-card-id"


def test_openai_adapter_uses_model_for_chitchat_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OpenAIPipiModelAdapter(fallback=DeterministicPipiModelAdapter())
    calls: list[list[dict[str, str]]] = []

    monkeypatch.setattr(
        model_adapter_module,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "openai_api_key": SecretStr("unit-test-key"),
                "openai_base_url": "https://api.openai.com/v1",
                "openai_model": "gpt-4.1-mini",
                "openai_timeout_seconds": 30.0,
            },
        )(),
    )

    def fake_chat_json(self: OpenAIPipiModelAdapter, *, messages: list[dict[str, str]]) -> dict[str, object]:
        calls.append(messages)
        return {"assistant_message": "你好，我是皮皮。"}

    monkeypatch.setattr(OpenAIPipiModelAdapter, "_chat_json", fake_chat_json)

    response = adapter.compose_response(
        {
            "conversation_id": "conversation-id",
            "user_turn_id": "turn-id",
            "user_message": "你好",
            "intent": "greeting",
            "context": {"facts": {}},
            "metadata": {},
        }
    )

    assert response == "你好，我是皮皮。"
    assert len(calls) == 1


def test_openai_adapter_rewrites_control_turns_before_local_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OpenAIPipiModelAdapter(fallback=DeterministicPipiModelAdapter())
    calls: list[list[dict[str, str]]] = []

    monkeypatch.setattr(
        model_adapter_module,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "openai_api_key": SecretStr("unit-test-key"),
                "openai_base_url": "https://api.openai.com/v1",
                "openai_model": "gpt-4.1-mini",
                "openai_timeout_seconds": 30.0,
            },
        )(),
    )

    def fake_chat_json(self: OpenAIPipiModelAdapter, *, messages: list[dict[str, str]]) -> dict[str, object]:
        calls.append(messages)
        return {"rewritten_query": "发出去", "reason": "Control turn audited by model.", "entities": {}}

    monkeypatch.setattr(OpenAIPipiModelAdapter, "_chat_json", fake_chat_json)

    rewrite = adapter.rewrite_query_for_state(
        {
            "conversation_id": "conversation-id",
            "user_turn_id": "turn-id",
            "user_message": "发出去",
            "context": {"facts": {}},
            "metadata": {},
        }
    )

    assert rewrite["method"] == "openai"
    assert rewrite["rewritten"] == "发出去"
    assert len(calls) == 1
    assert adapter.classify_intent("发出去") == "publish_help"
