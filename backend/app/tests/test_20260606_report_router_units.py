from __future__ import annotations

import pytest

from app.services.chat import (
    _area_food_route,
    _help_card_payload,
    _help_only_no_web,
    _known_venue_order_route,
    _needs_clarification_text,
    _travel_place_route,
)
from app.services.intent_router import detect_clarification_needed


@pytest.mark.parametrize(
    "message",
    [
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
def test_20260606_ambiguous_requests_need_clarification(message: str) -> None:
    assert detect_clarification_needed(message) is not None
    assert _needs_clarification_text("".join(message.split()))


@pytest.mark.parametrize(
    ("message", "venue_hint", "menu_context"),
    [
        ("我在一家你没听过的小店，第一次来，帮我点菜", "没听过的小店", "first_time"),
        ("我在一家没有线上菜单的小馆，第一次来，帮我点菜", "无线上菜单小馆", "no_online_menu"),
        ("我在只看到店招写着家常菜的店，两个人吃，帮我点菜", "店招家常菜小店", "sign_only"),
        ("我在一家菜单很多看不懂的小店，不太能吃辣，帮我点菜", "菜单很多看不懂的小店", "hard_menu"),
        ("我在一家菜单没写价格的小馆，预算别太高，帮我点菜", "菜单没写价格小馆", "no_price"),
        ("我在一个路边小摊，两个人吃，帮我点菜", "路边小摊", "stall"),
        ("我在一个没有名字的小摊，老板问我要什么", "无名小摊", "stall"),
    ],
)
def test_20260606_unknown_venue_ordering_stays_help_card_context(
    message: str,
    venue_hint: str,
    menu_context: str,
) -> None:
    assert detect_clarification_needed(message) is None
    assert _needs_clarification_text("".join(message.split())) is False
    assert _help_only_no_web(message)

    help_card = _help_card_payload(message)

    assert help_card["location_state"] == "in_venue"
    assert help_card["title"] not in {"北京这顿饭，求一个", "这家店怎么点，求一个"}
    assert help_card["context"]["venue_hint"] == venue_hint
    assert help_card["context"]["menu_context"] == menu_context
    assert help_card["context"]["task"] == "order_dishes"


def test_20260606_top10_area_food_still_routes_to_restaurant() -> None:
    message = "给我三里屯川菜Top10"

    assert detect_clarification_needed(message) is None
    assert _needs_clarification_text(message) is False
    route = _area_food_route(message)

    assert route is not None
    assert route["location_state"] == "in_area"
    assert route["target_type"] == "restaurant"


def test_20260606_haidilao_inside_beats_area_keyword() -> None:
    route = _known_venue_order_route("我坐在三里屯海底捞里面，两个人不吃辣，直接帮我点")

    assert route is not None
    assert route["location_state"] == "in_venue"
    assert route["target_type"] == "ordering_bundle"
    assert "三里屯川菜馆候选" not in route["title"]


def test_20260606_kyoto_food_is_restaurant_not_generic_place() -> None:
    route = _travel_place_route("我在京都，一个人晚上吃饭，不想排队，直接选一个")

    assert route is not None
    assert route["location_state"] == "in_area"
    assert route["target_type"] == "restaurant"


def test_20260606_seoul_beauty_still_routes_to_place() -> None:
    route = _travel_place_route("我第一次来首尔，想买美妆，别去明洞，直接选一个地方")

    assert route is not None
    assert route["location_state"] == "in_area"
    assert route["target_type"] == "place"
