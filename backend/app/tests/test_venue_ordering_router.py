from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PIPI_EVAL_MODE", "false")
    monkeypatch.setenv("ALLOW_EVAL_BYPASS", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def _chat(client: TestClient, message: str) -> dict[str, Any]:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": "manual-smoke-venue-ordering-router",
            "conversation_id": None,
            "message": message,
            "client_context": {
                "source": "manual",
                "benchmark_suite_id": "food_beijing_onsite_v1",
                "benchmark_case_id": "venue_ordering_router",
                "eval_run_id": "pytest",
                "include_debug": True,
                "mode": "remote_smoke",
                "pipi_eval_mode": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_haidilao_sanlitun_ordering_uses_venue_before_area(client: TestClient) -> None:
    body = _chat(client, "我在三里屯海底捞，两个人不太能吃辣，帮我点")

    assert body["location_state"] == "in_venue"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"

    card = body["data"]["recommendation_card"]
    assert card["target_type"] == "ordering_bundle"
    assert card["title"] == "番茄锅 + 牛肉/虾滑 + 蔬菜"
    assert card["subtitle"] == "海底捞 · 默认 2 人"
    assert card["decision_factor"]["text"] == "不知道怎么点时，番茄锅容错率最高。"
    assert "三里屯川菜馆候选" not in card["title"]


def test_sanlitun_sichuan_general_query_still_uses_area_restaurant(client: TestClient) -> None:
    body = _chat(client, "我到了北京三里屯，有什么好吃的川菜么")

    assert body["location_state"] == "in_area"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    assert body["data"]["recommendation_card"]["target_type"] == "restaurant"


def test_sanlitun_sichuan_pick_one_still_uses_area_restaurant(client: TestClient) -> None:
    body = _chat(client, "我在三里屯，想吃川菜，帮我选一家")

    assert body["location_state"] == "in_area"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    assert body["data"]["recommendation_card"]["target_type"] == "restaurant"
