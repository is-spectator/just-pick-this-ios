from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


FORBIDDEN_TERMS = ("Top 3", "榜单", "你可以考虑", "以下是几个", "推荐几个")


@pytest.fixture(autouse=True)
def explicit_smoke_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    monkeypatch.setenv("PIPI_CARD_COMPOSER", "deterministic")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "disabled")
    monkeypatch.setenv("PIPI_EVAL_MODE", "false")
    monkeypatch.setenv("ALLOW_EVAL_BYPASS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def _chat(client: TestClient, message: str, *, device_uid: str = "manual-smoke-pytest") -> dict[str, Any]:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": device_uid,
            "conversation_id": None,
            "message": message,
            "client_context": {
                "source": "manual",
                "benchmark_suite_id": "food_beijing_onsite_v1",
                "benchmark_case_id": "pytest",
                "eval_run_id": "pytest",
                "include_debug": True,
                "mode": "remote_smoke",
                "pipi_eval_mode": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_openapi_expose_chat_turn() -> None:
    with _client() as client:
        health = client.get("/health")
        assert health.status_code == 200

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        paths = openapi.json()["paths"]
        assert "/v1/chat/turn" in paths
        assert "post" in paths["/v1/chat/turn"]
        assert "/v1/cards/{card_id}" in paths
        assert "get" in paths["/v1/cards/{card_id}"]
        assert "/v1/help-cards/{help_card_id}" in paths
        assert "get" in paths["/v1/help-cards/{help_card_id}"]


def test_smoke_sanlitun_sichuan_returns_single_card() -> None:
    with _client() as client:
        body = _chat(client, "我到了北京三里屯，有什么好吃的川菜么")
        assert body["location_state"] == "in_area"
        assert body["ui_events"] == [
            {"type": "show_recommendation_card", "card_id": body["data"]["recommendation_card"]["id"]}
        ]
        card = body["data"]["recommendation_card"]
        assert card["target_type"] == "restaurant"
        assert card["decision_factor"]["key"] == "nearby_sichuan_stable"
        assert card["image"] is None
        assert "decision_factors" not in card
        for term in FORBIDDEN_TERMS:
            assert term not in str(card)

        fetched = client.get(f"/v1/cards/{card['id']}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["card"]["id"] == card["id"]


def test_smoke_sijiminfu_ordering_returns_single_card() -> None:
    with _client() as client:
        body = _chat(client, "我在四季民福故宫店，第一次来怎么点菜")
        card = body["data"]["recommendation_card"]
        assert body["location_state"] == "in_venue"
        assert body["ui_events"][0]["type"] == "show_recommendation_card"
        assert card["target_type"] == "ordering_bundle"
        assert card["title"] == "烤鸭 + 清爽配菜 + 甜品"
        assert card["decision_factor"]["text"] == "第一次来四季民福，先吃招牌，口味最稳。"
        for term in FORBIDDEN_TERMS:
            assert term not in str(card)


def test_smoke_unknown_area_guizhou_returns_help_card() -> None:
    with _client() as client:
        body = _chat(client, "我在北京一个很偏的地方，想吃贵州菜")
        help_card = body["data"]["help_card"]
        assert body["ui_events"][0]["type"] == "show_help_card_draft"
        assert help_card["title"] == "偏远位置想吃贵州菜，求一个"
        assert help_card["location_state"] == "unknown"
        assert help_card["context"]["location_hint"] == "偏远位置"
        assert help_card["context"]["food_preference"] == "贵州菜"

        fetched = client.get(f"/v1/help-cards/{help_card['id']}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["help_card"]["id"] == help_card["id"]


def test_smoke_unknown_venue_ordering_returns_help_card() -> None:
    with _client() as client:
        body = _chat(client, "我在一家没听过的小店，怎么点菜")
        help_card = body["data"]["help_card"]
        assert body["ui_events"][0]["type"] == "show_help_card_draft"
        assert help_card["title"] == "没听过的小店怎么点，求一句稳的"
        assert help_card["location_state"] == "in_venue"
        assert help_card["context"]["venue"] == "未知小店"
        assert help_card["context"]["venue_hint"] == "没听过的小店"
