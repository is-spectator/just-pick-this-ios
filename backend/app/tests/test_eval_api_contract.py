from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def eval_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("PIPI_EVAL_MODE", "true")
    monkeypatch.setenv("ALLOW_EVAL_BYPASS", "true")
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    monkeypatch.setenv("PIPI_CARD_COMPOSER", "deterministic")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "disabled")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def _reset_and_seed(client: TestClient) -> None:
    reset = client.post("/v1/eval/reset", json={"eval_run_id": "pytest-eval-run"})
    assert reset.status_code == 200, reset.text
    seeded = client.post(
        "/v1/eval/seed/food-beijing-onsite-v1",
        json={"mode": "minimal", "with_approved_answers": True},
    )
    assert seeded.status_code == 200, seeded.text


def _chat(client: TestClient, *, device_uid: str, message: str) -> dict[str, Any]:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": device_uid,
            "conversation_id": None,
            "message": message,
            "client_context": {
                "source": "pipi-eval-lab",
                "benchmark_suite_id": "food_beijing_onsite_v1",
                "benchmark_case_id": "pytest",
                "eval_run_id": "pytest-eval-run",
                "include_debug": True,
                "pipi_eval_mode": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_eval_health_reset_and_seed(eval_client: TestClient) -> None:
    health = eval_client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["service"] == "just-pick-this-ios-backend"
    assert body["eval_mode"] is True

    reset = eval_client.post("/v1/eval/reset", json={"eval_run_id": "pytest-eval-run"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["ok"] is True

    seeded = eval_client.post(
        "/v1/eval/seed/food-beijing-onsite-v1",
        json={"mode": "minimal", "with_approved_answers": True},
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["seeded"] == {
        "area_anchors": 1,
        "venues": 1,
        "area_intent_answers": 1,
        "ordering_bundle_answers": 1,
    }


def test_eval_chat_returns_area_restaurant_card(eval_client: TestClient) -> None:
    _reset_and_seed(eval_client)

    body = _chat(
        eval_client,
        device_uid="eval-device-area-card",
        message="我到了北京三里屯，有什么好吃的川菜么",
    )

    assert body["location_state"] == "in_area"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == "restaurant"
    assert isinstance(card["decision_factor"], dict)
    assert "decision_factor" in card
    assert "decision_factors" not in card
    assert card["image"] is None or card["image"]["is_ai_generated"] is False
    if card["image"] is not None:
        assert card["image"]["source_url"]
        assert card["image"]["source_domain"]


def test_eval_chat_returns_venue_ordering_bundle_card(eval_client: TestClient) -> None:
    _reset_and_seed(eval_client)

    body = _chat(
        eval_client,
        device_uid="eval-device-venue-card",
        message="我在四季民福故宫店，第一次来两个人怎么点菜",
    )

    assert body["location_state"] == "in_venue"
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == "ordering_bundle"
    assert card["title"] == "烤鸭 + 清爽配菜 + 甜品"
    assert card["decision_factor"]["text"] == "第一次来四季民福，先吃招牌，口味最稳。"


def test_eval_unknown_area_and_venue_return_help_cards(eval_client: TestClient) -> None:
    _reset_and_seed(eval_client)

    area_body = _chat(
        eval_client,
        device_uid="eval-device-unknown-area",
        message="我在一个未知商圈附近，想吃川菜，就选一个",
    )
    area_help = area_body["data"]["help_card"]
    assert area_body["ui_events"][0]["type"] == "show_help_card_draft"
    assert area_help["title"]
    assert isinstance(area_help["context"], dict)
    assert area_help["wants"]
    assert area_help["avoids"]
    assert area_help["constraints"]

    venue_body = _chat(
        eval_client,
        device_uid="eval-device-unknown-venue",
        message="我在不存在餐厅点菜，第一次来怎么点",
    )
    assert venue_body["ui_events"][0]["type"] == "show_help_card_draft"
    assert venue_body["data"]["help_card"]["location_state"] == "in_venue"


def test_eval_card_and_help_card_fetch_endpoints(eval_client: TestClient) -> None:
    _reset_and_seed(eval_client)

    card_body = _chat(
        eval_client,
        device_uid="eval-device-fetch-card",
        message="三里屯川菜帮我选一家",
    )
    card_id = card_body["data"]["recommendation_card"]["id"]
    card_response = eval_client.get(f"/v1/cards/{card_id}")
    assert card_response.status_code == 200, card_response.text
    assert card_response.json()["id"] == card_id
    assert card_response.json()["type"] == "recommendation_card"

    help_body = _chat(
        eval_client,
        device_uid="eval-device-fetch-help",
        message="我在一个陌生地方，附近吃什么",
    )
    help_card_id = help_body["data"]["help_card"]["id"]
    help_response = eval_client.get(f"/v1/help-cards/{help_card_id}")
    assert help_response.status_code == 200, help_response.text
    assert help_response.json()["id"] == help_card_id
    assert help_response.json()["type"] == "help_card"


def test_eval_help_feed_and_one_liner(eval_client: TestClient) -> None:
    _reset_and_seed(eval_client)

    body = _chat(
        eval_client,
        device_uid="eval-device-help-owner",
        message="我在一个陌生地方，附近吃什么",
    )
    help_card_id = body["data"]["help_card"]["id"]
    published = eval_client.post(
        f"/v1/help-cards/{help_card_id}/publish",
        json={"device_uid": "eval-device-help-owner"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["help_card"]["status"] == "published"

    owner_feed = eval_client.get("/v1/help-feed", params={"device_uid": "eval-device-help-owner"})
    assert owner_feed.status_code == 200, owner_feed.text
    assert help_card_id not in {item["id"] for item in owner_feed.json()["items"]}

    answer = eval_client.post(
        f"/v1/help-cards/{help_card_id}/one-liner",
        json={
            "device_uid": "eval-answer-user-001",
            "text": "别纠结了，三里屯这题我会选那家川菜，近一点更稳。",
        },
    )
    assert answer.status_code == 200, answer.text
    answer_body = answer.json()
    assert answer_body["answer"]["status"] == "submitted"
    assert answer_body["help_card"]["answer_count"] == 1
    assert answer_body["toast"] == "收到了，+10 等她采纳。"


def test_eval_trace_by_turn(eval_client: TestClient) -> None:
    _reset_and_seed(eval_client)
    body = _chat(
        eval_client,
        device_uid="eval-device-trace",
        message="我到了北京三里屯，有什么好吃的川菜么",
    )

    trace = eval_client.get(f"/v1/eval/traces/turns/{body['turn_id']}")
    assert trace.status_code == 200, trace.text
    trace_body = trace.json()
    assert trace_body["turn_id"] == body["turn_id"]
    assert trace_body["agent_run"]["id"] == body["debug"]["agent_run_id"]
    assert trace_body["tool_calls"]
    assert trace_body["retrieval_run"]["id"] == body["debug"]["retrieval_run_id"]
    assert trace_body["retrieval_hits"]


def test_eval_routes_are_disabled_when_eval_mode_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPI_EVAL_MODE", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.post("/v1/eval/reset", json={"eval_run_id": "pytest-eval-run"})
    get_settings.cache_clear()
    assert response.status_code in {403, 404}
