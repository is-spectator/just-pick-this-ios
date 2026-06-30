from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.agent import model_adapter as model_adapter_module
from app.agent.model_adapter import OpenAIPipiModelAdapter, get_deterministic_model_adapter
from app.db import make_session_factory
from app.models import AgentRun

from .conftest import bootstrap, chat_turn


@pytest.mark.anyio
async def test_short_followup_uses_previous_session_turns(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-history-followup")
    conversation_id = boot["conversation_id"]

    first = await chat_turn(
        async_client,
        message="我在北京故宫",
        conversation_id=conversation_id,
    )
    assert first["metadata"]["intent"]["name"] == "unknown"
    assert first["cards"] == []
    assert first["help_cards"] == []

    second = await chat_turn(
        async_client,
        message="吃的",
        conversation_id=conversation_id,
    )

    assert second["metadata"]["intent"]["name"] == "decision_request"
    assert second["metadata"]["retrieval_run_id"]
    assert second["help_cards"], second
    assert "北京故宫" in second["help_cards"][0]["prompt"]

    session_factory = make_session_factory()
    with session_factory() as session:
        latest_trace = session.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == uuid.UUID(conversation_id))
            .order_by(AgentRun.created_at.desc())
        ).first()

    assert latest_trace is not None
    output_json = latest_trace.output_json or {}
    facts = output_json["context"]["facts"]
    assert facts["latest_user_context"] == "我在北京故宫"
    assert facts["resolved_user_message"] == "我在北京故宫；吃的"
    assert len(output_json["context"]["recent_turns"]) >= 3


@pytest.mark.anyio
async def test_greeting_variant_does_not_use_unknown_fallback(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-greeting-variant")

    body = await chat_turn(
        async_client,
        message="你好呀",
        conversation_id=boot["conversation_id"],
    )

    assert body["metadata"]["intent"]["name"] == "greeting"
    assert body["tool_calls"] == []
    assert body["cards"] == []
    assert body["help_cards"] == []
    assert "你好，我是皮皮" in body["assistant_message"]
    assert "你想在这附近找吃的" not in body["assistant_message"]


@pytest.mark.anyio
async def test_location_only_acknowledges_location_without_repeating_prompt(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-location-ack")

    body = await chat_turn(
        async_client,
        message="我在北京王府井呢",
        conversation_id=boot["conversation_id"],
    )

    assert body["metadata"]["intent"]["name"] == "unknown"
    assert body["tool_calls"] == []
    assert body["cards"] == []
    assert body["help_cards"] == []
    assert "你在北京王府井" in body["assistant_message"]
    assert "你想在这附近找吃的" not in body["assistant_message"]


@pytest.mark.anyio
async def test_food_preference_followup_inherits_previous_location(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-food-preference-location")
    conversation_id = boot["conversation_id"]

    first = await chat_turn(
        async_client,
        message="我想吃川菜",
        conversation_id=conversation_id,
    )
    assert first["response_kind"] == "clarification"

    second = await chat_turn(
        async_client,
        message="我在上海互联宝地",
        conversation_id=conversation_id,
    )
    assert second["metadata"]["intent"]["name"] == "unknown"
    assert "上海互联宝地" in second["assistant_message"]

    third = await chat_turn(
        async_client,
        message="我想吃川菜啊",
        conversation_id=conversation_id,
    )

    assert third["response_kind"] != "clarification"
    assert third["metadata"]["intent"]["name"] == "decision_request"
    assert third["metadata"]["input_gate"]["route_priority"] == "area_food"
    assert third["metadata"]["input_gate"]["location_state"] == "in_area"
    assert third["metadata"]["input_gate"]["extracted_slots"]["area"] == "互联宝地"
    assert third["metadata"]["input_gate"]["extracted_slots"]["cuisine"] == "川菜"
    assert "你现在在哪个位置" not in third["assistant_message"]


@pytest.mark.anyio
async def test_complaint_about_repetition_uses_session_context(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-repeat-complaint")
    conversation_id = boot["conversation_id"]

    await chat_turn(
        async_client,
        message="我在北京王府井呢",
        conversation_id=conversation_id,
    )
    body = await chat_turn(
        async_client,
        message="你怎么说重复我话",
        conversation_id=conversation_id,
    )

    assert body["metadata"]["intent"]["name"] == "smalltalk"
    assert body["tool_calls"] == []
    assert body["cards"] == []
    assert body["help_cards"] == []
    assert "北京王府井" in body["assistant_message"]
    assert "你想在这附近找吃的" not in body["assistant_message"]


@pytest.mark.anyio
async def test_restaurant_order_request_creates_question_and_does_not_fail(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-restaurant-order")

    body = await chat_turn(
        async_client,
        message="我被北京故宫的四季民福，你帮我点个菜吧？",
        conversation_id=boot["conversation_id"],
    )

    assert body["metadata"]["intent"]["name"] in {"decision_request", "help_request"}
    assert body["tool_calls"], body
    assert body["tool_calls"][0]["status"] != "failed"
    assert "这轮没处理成功" not in body["assistant_message"]
    assert body["help_cards"] or body["cards"]


@pytest.mark.anyio
async def test_ios_request_uses_real_runtime_and_sijiminfu_ordering_beats_active_help_card(
    async_client,
    monkeypatch,
) -> None:
    from app.services import smoke_runtime

    monkeypatch.setattr(
        smoke_runtime,
        "run_smoke_chat_turn",
        lambda payload: pytest.fail("iOS requests without eval client_context must not use smoke runtime"),
    )

    first_response = await async_client.post(
        "/v1/chat/turn",
        json={
            "device_id": "ios-real-runtime-regression",
            "message": "韩国逛街，不去明洞，想小众",
            "metadata": {},
        },
    )
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    assert first["help_cards"], first

    second_response = await async_client.post(
        "/v1/chat/turn",
        json={
            "device_id": "ios-real-runtime-regression",
            "conversation_id": first["conversation_id"],
            "message": "好吧，那我在四季民福，点什么菜呢",
            "metadata": {},
        },
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()

    assert second["cards"], second
    assert second["help_cards"] == []
    assert second["cards"][0]["title"] == "烤鸭 + 清爽配菜 + 甜品"
    assert second["cards"][0]["target_type"] == "ordering_bundle"
    assert second["cards"][0]["decision_factor"]["text"] == "第一次来四季民福，先吃招牌，口味最稳。"
    tool_names = [tool["name"] for tool in second["tool_calls"]]
    assert "search_knowledge" in tool_names
    assert "create_recommendation_card" in tool_names
    assert tool_names.index("search_knowledge") < tool_names.index("create_recommendation_card")


@pytest.mark.anyio
async def test_followup_after_help_card_updates_active_card_instead_of_failing(async_client) -> None:
    boot = await bootstrap(async_client, device_id="contextual-active-help-followup")
    conversation_id = boot["conversation_id"]

    first = await chat_turn(
        async_client,
        message="我在北京一个很偏的地方，想吃特别小众的贵州菜",
        conversation_id=conversation_id,
    )
    assert first["help_cards"], first

    second = await chat_turn(
        async_client,
        message="可是有哪些肉店呢",
        conversation_id=conversation_id,
    )

    assert "这轮没处理成功" not in second["assistant_message"]
    assert any(tool["name"] == "update_help_card" for tool in second["tool_calls"]), second
    assert all(tool["status"] != "failed" for tool in second["tool_calls"])
    assert second["help_cards"], second
    assert second["help_cards"][0]["id"] == first["help_cards"][0]["id"]


def test_location_ack_wins_even_if_model_misclassifies_as_smalltalk() -> None:
    adapter = get_deterministic_model_adapter()

    message = adapter.compose_response(
        {
            "conversation_id": "conversation",
            "user_turn_id": "turn",
            "user_message": "我在北京王府井呢",
            "intent": "smalltalk",
            "context": {"facts": {}},
            "metadata": {},
        }
    )

    assert "你在北京王府井" in message
    assert "少纠结" not in message


def test_openai_router_cannot_downgrade_card_ready_evidence_to_help(monkeypatch) -> None:
    fallback = get_deterministic_model_adapter()
    adapter = OpenAIPipiModelAdapter(fallback=fallback)
    monkeypatch.setattr(
        model_adapter_module,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"openai_api_key": SecretStr("unit-test-key")},
        )(),
    )

    next_action, tool_call = adapter.decide_next_action(
        {
            "conversation_id": "conversation",
            "user_turn_id": "turn",
            "user_message": "我在四季民福，帮我点个菜",
            "intent": "help_request",
            "retrieval_hits": [
                {
                    "source_id": "hit",
                    "score": 0.86,
                    "payload": {
                        "has_answer_evidence": True,
                        "has_verified_non_ai_image": True,
                        "image_asset_id": "image",
                    },
                }
            ],
            "metadata": {},
        }
    )

    assert next_action == "call_tool"
    assert tool_call is not None
    assert tool_call["name"] == "create_recommendation_card"
