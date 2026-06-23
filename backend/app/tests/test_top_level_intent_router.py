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
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    monkeypatch.setenv("PIPI_CARD_COMPOSER", "deterministic")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def _chat(client: TestClient, message: str) -> dict[str, Any]:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": "manual-smoke-top-level-router",
            "conversation_id": None,
            "message": message,
            "client_context": {
                "source": "manual",
                "benchmark_suite_id": "pipi_system_ground_truth_100_v1",
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


def test_product_chat_turn_without_debug_flag_omits_debug_field(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": "manual-product-no-debug",
            "conversation_id": None,
            "message": "你好",
            "client_context": {"source": "manual"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_kind"] == "chitchat"
    assert body["ui_events"] == []
    assert "debug" not in body


@pytest.mark.parametrize(
    "message",
    ["你好", "嗨", "早上好", "谢谢你", "你是谁", "讲个短笑话", "晚安", "随便说点什么"],
)
def test_chitchat_returns_text_no_card(client: TestClient, message: str) -> None:
    body = _chat(client, message)

    assert body["response_kind"] == "chitchat"
    assert body["location_state"] == "unknown"
    assert body["ui_events"] == []
    assert body["data"] == {}
    assert body["assistant_message"]
    assert "help_card" not in body["data"]
    assert "recommendation_card" not in body["data"]
    assert body["debug"]["selected_tool"] is None


@pytest.mark.parametrize(
    "message",
    [
        "我想吃饭",
        "今晚吃什么",
        "我想吃辣的",
        "两个人吃饭帮我挑",
        "想吃点不贵的",
        "我在北京，吃什么",
        "带朋友吃饭去哪",
        "帮我选一家",
        "帮我点菜",
        "我想吃火锅",
        "附近有什么好吃的",
        "想吃甜品",
        "带爸妈吃饭去哪",
        "想吃小吃",
        "想买个小屏",
        "想买个充电宝",
        "出去玩去哪",
        "想逛街去哪",
        "想买伴手礼",
        "附近咖啡给我选一个",
        "菜单太多帮我看",
        "想吃特别一点",
        "想吃健康点",
        "快点帮我选一个",
        "想找个安静地方",
        "想吃素",
        "想找个地方待一会",
        "不吃辣帮我选",
        "半天去哪玩",
        "我想买电烙铁，顺便附近吃点啥",
        "我拍了菜单但你看不到，帮我点",
    ],
)
def test_ambiguous_food_needs_clarification(client: TestClient, message: str) -> None:
    body = _chat(client, message)

    assert body["response_kind"] == "clarification"
    assert body["ui_events"] == []
    assert body["assistant_message"]
    assert body["data"]["clarification"]["missing_slots"]
    assert "help_card" not in body["data"]
    assert "recommendation_card" not in body["data"]
    assert body["debug"]["selected_tool"] is None


@pytest.mark.parametrize(
    "message",
    [
        "我在北京三里屯海底捞，预算别太夸张，帮我点",
        "我在北京故宫四季民福，预算别太夸张，帮我点",
        "我在北京望京西贝，预算别太夸张，帮我点",
        "我在上海南京西路陶陶居，预算别太夸张，帮我点",
        "我在北京国贸喜晋道，预算别太夸张，帮我点",
        "我在北京牛街聚宝源，预算别太夸张，帮我点",
        "我在上海静安寺大董，预算别太夸张，帮我点",
        "我在成都太古里海底捞，预算别太夸张，帮我点",
        "我在北京西单麦当劳，预算别太夸张，帮我点",
        "我在广州天河点都德，预算别太夸张，帮我点",
    ],
)
def test_venue_budget_ordering_returns_bundle_not_update_help(client: TestClient, message: str) -> None:
    body = _chat(client, message)
    card = body["data"]["recommendation_card"]

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "in_venue"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    assert card["target_type"] == "ordering_bundle"
    assert body["debug"]["selected_tool"] == "create_recommendation_card"


@pytest.mark.parametrize(
    "message",
    [
        "我想买咖啡手冲壶，别折腾，稳定就行，你直接帮我选一个",
        "我想买咖啡手冲壶，想轻一点，你直接帮我选一个",
        "我想买咖啡手冲壶，新手用，你直接帮我选一个",
        "我想买树莓派小屏，预算别太高，你直接帮我选一个",
    ],
)
def test_product_budget_or_coffee_decision_is_not_help_update(client: TestClient, message: str) -> None:
    body = _chat(client, message)
    card = body["data"]["recommendation_card"]

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "unknown"
    assert card["target_type"] == "product"
    assert body["debug"]["selected_tool"] == "create_recommendation_card"


@pytest.mark.parametrize(
    "message",
    [
        "四季民福烤鸭怎么点",
        "四季民福别浪费怎么点",
        "四季民福想吃清淡一点",
        "四季民福你帮我决定",
        "四季民福带家人怎么点",
        "第一次来四季民福",
        "四季民福想快点点完",
    ],
)
def test_sijiminfu_paraphrases_return_ordering_bundle(client: TestClient, message: str) -> None:
    body = _chat(client, message)
    card = body["data"]["recommendation_card"]

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "in_venue"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    assert card["target_type"] == "ordering_bundle"
    assert set(card) >= {"decision_factor"}
    assert "decision_factors" not in card


@pytest.mark.parametrize(
    "message",
    [
        "海底捞番茄锅怎么点",
        "我到海底捞了",
        "海底捞朋友局怎么点",
        "海底捞快点帮我点",
        "海底捞你决定",
    ],
)
def test_haidilao_paraphrases_return_ordering_bundle(client: TestClient, message: str) -> None:
    body = _chat(client, message)
    card = body["data"]["recommendation_card"]

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "in_venue"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    assert card["target_type"] == "ordering_bundle"
    assert set(card) >= {"decision_factor"}
    assert "decision_factors" not in card


@pytest.mark.parametrize(
    "message",
    [
        "我在北京一个很偏的地方，想吃特别小众的贵州菜",
        "我在一家你没听过的小店，帮我点菜",
        "我在一家很小的面馆，第一次来，帮我点",
        "我在一家没有线上菜单的小馆，第一次来，帮我点菜",
        "我在只看到店招写着家常菜的店，两个人吃，帮我点菜",
        "我在一家菜单很多看不懂的小店，不太能吃辣，帮我点菜",
        "我在一家菜单没写价格的小馆，预算别太高，帮我点菜",
        "我在一个路边小摊，两个人吃，帮我点菜",
        "我在一个没有名字的小摊，老板问我要什么",
    ],
)
def test_specific_unknown_context_returns_help_card(client: TestClient, message: str) -> None:
    body = _chat(client, message)
    help_card = body["data"]["help_card"]

    assert body["response_kind"] == "help_card_draft"
    assert body["ui_events"][0]["type"] == "show_help_card_draft"
    assert help_card["title"]
    assert help_card["context"]


@pytest.mark.parametrize(
    ("message", "title_terms", "context_keys"),
    [
        ("我在北京一个很偏的地方，想吃特别小众的贵州菜", ["偏远位置", "贵州菜"], {"location_hint", "food_preference"}),
        ("我在北京一个说不清楚的位置，想吃客家菜", ["位置说不清", "客家菜"], {"location_hint", "food_preference"}),
        ("我在北京郊区一条小路上，想吃朝鲜族菜", ["郊区小路", "朝鲜族菜"], {"location_hint", "food_preference"}),
        ("我在北京一个公园边上，想吃严格素食但不知道附近有什么", ["公园边", "素食"], {"location_hint", "food_preference"}),
        ("我在北京一个工业区，想吃咖喱饭", ["工业区", "咖喱饭"], {"location_hint", "food_preference"}),
    ],
)
def test_area_help_card_title_and_context_are_specific(
    client: TestClient,
    message: str,
    title_terms: list[str],
    context_keys: set[str],
) -> None:
    body = _chat(client, message)
    help_card = body["data"]["help_card"]
    context = help_card["context"]

    assert body["response_kind"] == "help_card_draft"
    assert help_card["title"] not in {"北京这顿饭，求一个", "这顿饭，求一个", "这家店怎么点，求一个"}
    for term in title_terms:
        assert term in help_card["title"]
    assert context_keys <= set(context)
    assert len([value for value in context.values() if value]) > 1


@pytest.mark.parametrize(
    ("message", "title_term", "menu_context"),
    [
        ("我在一家你没听过的小店，帮我点菜", "没听过的小店", "unknown_menu"),
        ("我在一家没有线上菜单的小馆子，你帮我看看怎么点", "无线上菜单小馆", "no_online_menu"),
        ("我在一家刚开的店，网上应该没资料，帮我点", "刚开新店", "new_opening"),
        ("我在一家很小的面馆，第一次来，帮我点", "小面馆", "first_time"),
        ("我在一家手写菜单的小店，菜名很多，帮我点一下", "手写菜单小店", "handwritten_menu"),
        ("我在只看到店招写着家常菜的店，两个人吃，帮我点菜", "店招家常菜小店", "sign_only"),
        ("我在一家菜单很多看不懂的小店，不太能吃辣，帮我点菜", "菜单很多看不懂的小店", "hard_menu"),
        ("我在一家菜单没写价格的小馆，预算别太高，帮我点菜", "菜单没写价格小馆", "no_price"),
        ("我在一个路边小摊，两个人吃，帮我点菜", "路边小摊", "stall"),
        ("我在一个没有名字的小摊，老板问我要什么", "无名小摊", "stall"),
    ],
)
def test_venue_help_card_title_and_context_are_specific(
    client: TestClient,
    message: str,
    title_term: str,
    menu_context: str,
) -> None:
    body = _chat(client, message)
    help_card = body["data"]["help_card"]
    context = help_card["context"]

    assert body["response_kind"] == "help_card_draft"
    assert help_card["title"] not in {"北京这顿饭，求一个", "这顿饭，求一个", "这家店怎么点，求一个"}
    assert title_term in help_card["title"]
    assert context["venue_hint"] == title_term
    assert context["menu_context"] == menu_context
    assert context["task"] == "order_dishes"
