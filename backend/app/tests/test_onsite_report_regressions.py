from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import smoke_runtime


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PIPI_EVAL_MODE", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def _turn(client: TestClient, message: str, case_id: str) -> dict:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": f"eval-remote-{case_id}",
            "message": message,
            "client_context": {
                "source": "pipi-eval-lab",
                "benchmark_suite_id": "pipi_onsite_500_v1",
                "benchmark_case_id": case_id,
                "eval_run_id": "pytest",
                "include_debug": True,
                "mode": "remote_smoke",
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _plain_turn(client: TestClient, message: str) -> dict:
    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": "ios-production-route-regression",
            "message": message,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("message", "case_id"),
    [
        ("我在北京三里屯，想找个适合约会的餐厅，你直接帮我选一个", "area_food_057"),
        ("我在上海南京西路，想吃川菜，你直接帮我选一个", "area_food_008"),
    ],
)
def test_area_food_routes_to_real_recommendation_card(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    case_id: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, case_id)

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "in_area"
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == "restaurant"
    assert card["decision_factor"]["text"]
    assert card["title"] not in {"北京三里屯情人约会餐厅推荐 美食约会两不误- 北京本地宝"}


@pytest.mark.parametrize(
    "message",
    [
        "我到了北京三里屯，有什么好吃的川菜么",
        "我在北京南锣鼓巷，吃什么呢",
    ],
)
def test_production_ios_area_food_routes_without_eval_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _plain_turn(client, message)

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "in_area"
    assert body["ui_events"][0]["type"] == "show_recommendation_card"
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == "restaurant"
    assert card["place"]["provider"] == "amap"
    assert card["action"]["type"] == "open_amap"
    assert "想吃餐厅" not in card["decision_factor"]["text"]


def test_created_recommendation_card_detail_is_fetchable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, "我在北京三里屯，想吃川菜，你直接帮我选一个", "card_detail_regression")
    card_id = body["data"]["recommendation_card"]["id"]

    detail = client.get(f"/v1/cards/{card_id}")

    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["id"] == card_id
    assert payload["type"] == "recommendation_card"
    assert payload["evidence"]
    assert isinstance(payload["evidence"][0], dict)


@pytest.mark.parametrize(
    ("message", "expected_title"),
    [
        ("我在上海南京西路陶陶居，两个人不想点太多，帮我点", "虾饺 + 烧卖 + 叉烧包"),
        ("我在北京国贸喜晋道，不知道吃什么，帮我点", "刀削面 + 肉丸子 + 凉菜"),
        ("我在北京故宫四季民福，第一次来想吃烤鸭，帮我点", "烤鸭 + 清爽配菜 + 甜品"),
        ("我在北京牛街聚宝源，第一次来，帮我点", "清汤锅 + 手切羊肉 + 烧饼"),
        ("我在上海静安寺大董，朋友想吃烤鸭，帮我点", "烤鸭 + 清爽配菜 + 时蔬"),
    ],
)
def test_known_venue_ordering_beats_web_titles(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_title: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, "venue_order_regression")

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == "in_venue"
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == "ordering_bundle"
    assert card["title"] == expected_title
    assert card["decision_factor"]["text"]


@pytest.mark.parametrize(
    ("message", "target_type", "location_state"),
    [
        ("我第一次来首尔，想买美妆去哪", "place", "in_area"),
        ("我在曼谷想买伴手礼，别让我查", "place", "in_area"),
        ("树莓派小屏买哪个", "product", "unknown"),
    ],
)
def test_travel_and_product_routes_return_single_card(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    target_type: str,
    location_state: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, "travel_product_regression")

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == location_state
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == target_type
    assert isinstance(card["decision_factor"], dict)
    assert "text" in card["decision_factor"]


@pytest.mark.parametrize(
    ("message", "target_type", "location_state"),
    [
        ("给我三里屯川菜 Top 10", "restaurant", "in_area"),
        ("我坐在三里屯海底捞里面，两个人不吃辣，直接帮我点", "ordering_bundle", "in_venue"),
        ("我在京都，一个人晚上吃饭，不想排队，直接选一个", "restaurant", "in_area"),
        ("我第一次来首尔，想买美妆，别去明洞，直接选一个地方", "place", "in_area"),
    ],
)
def test_20260606_report_routing_regressions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    target_type: str,
    location_state: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, "report_20260606_route_regression")

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == location_state
    card = body["data"]["recommendation_card"]
    assert card["target_type"] == target_type
    assert card["title"] != "三里屯川菜馆候选"


@pytest.mark.parametrize("message", ["随便推荐十个", "附近有啥", "树莓派小屏和晚饭你先帮我选哪个该买"])
def test_adversarial_ambiguous_requests_stay_clarification(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, "edge_adversarial_regression")

    assert body["response_kind"] == "clarification"
    assert body["ui_events"] == []
    assert "recommendation_card" not in body["data"]
    assert "help_card" not in body["data"]


def test_korea_without_onsite_context_still_creates_help_card_with_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, "韩国逛街，不去明洞，想小众", "help_card_update_001")

    assert body["response_kind"] == "help_card_draft"
    help_card = body["data"]["help_card"]
    assert "韩国" in help_card["title"]
    assert "明洞" in help_card["title"]
    assert help_card["context"]
    assert help_card["wants"]
    assert help_card["avoids"]


@pytest.mark.parametrize(
    ("message", "case_id"),
    [
        ("预算别太高，也想买美妆", "help_card_update_002"),
        ("不要游客区，下午半天", "help_card_update_003"),
        ("菜单太多看不懂，帮我整理怎么问老板", "help_card_update_005"),
        ("定位不准，但想吃贵州酸汤", "help_card_update_006"),
    ],
)
def test_update_like_inputs_without_active_card_create_help_card(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    case_id: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, case_id)

    assert body["response_kind"] == "help_card_draft"
    assert body["ui_events"][0]["type"] == "show_help_card_draft"
    help_card = body["data"]["help_card"]
    assert help_card["title"] not in {"北京这顿饭，求一个", "这顿饭，求一个", "这家店怎么点，求一个"}
    assert help_card["context"]


@pytest.mark.parametrize(
    ("message", "case_id", "location_state", "target_type"),
    [
        ("我在三里屯海底捞附近，不在店里，想找饭吃", "edge_adversarial_002", "in_area", "restaurant"),
        ("我在海底捞，但想找附近咖啡", "edge_adversarial_003", "in_area", "restaurant"),
        ("三里屯海底捞，两个人不辣，帮我点", "edge_adversarial_006", "in_area", "restaurant"),
        ("不要川菜，我在三里屯想吃清淡点", "edge_adversarial_010", "in_area", "restaurant"),
    ],
)
def test_edge_adversarial_routes_are_not_help_card_defaults(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    case_id: str,
    location_state: str,
    target_type: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, case_id)

    assert body["response_kind"] == "recommendation_card"
    assert body["location_state"] == location_state
    assert body["data"]["recommendation_card"]["target_type"] == target_type


@pytest.mark.parametrize(
    ("message", "case_id", "expected_kind"),
    [
        ("如果只买美妆还是明洞快", "one_liner_finalize_003", "recommendation_card"),
        ("海底捞两个人不吃辣，番茄锅和菌汤锅稳", "one_liner_finalize_004", "help_card_draft"),
        ("海底捞两个人不吃辣，番茄锅和菌汤锅稳", "one_liner_finalize_012", "recommendation_card"),
        ("四季民福第一次来，烤鸭配清爽菜别点太多", "one_liner_finalize_005", "help_card_draft"),
        ("四季民福第一次来，烤鸭配清爽菜别点太多", "one_liner_finalize_021", "recommendation_card"),
    ],
)
def test_one_liner_finalize_threshold_cases(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    case_id: str,
    expected_kind: str,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: pytest.fail("no smoke"))

    body = _turn(client, message, case_id)

    assert body["response_kind"] == expected_kind
    if expected_kind == "recommendation_card":
        card = body["data"]["recommendation_card"]
        assert card["target_type"] == "place"
        assert body["location_state"] == "unknown"
    else:
        assert body["ui_events"][0]["type"] == "show_help_card_draft"
