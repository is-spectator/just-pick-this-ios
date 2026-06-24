from __future__ import annotations

from app.harness.input_gate import run_input_gate


def test_area_food_hot_dry_noodle_slots() -> None:
    gate = run_input_gate("帮我找一下北京市朝阳区最好吃的热干面")

    assert gate.decision_domain == "food"
    assert gate.location_state == "in_area"
    assert gate.route_priority == "area_food"
    assert gate.should_enter_loop
    assert gate.should_retrieve
    assert gate.extracted_slots["city"] == "北京"
    assert gate.extracted_slots["area"] == "朝阳区"
    assert gate.extracted_slots["food_item"] == "热干面"


def test_wangjing_soho_guangdong_light_slots() -> None:
    gate = run_input_gate("我在望京 SOHO，广东人，想吃清淡点")

    assert gate.decision_domain == "food"
    assert gate.location_state == "in_area"
    assert gate.route_priority == "area_food"
    assert gate.extracted_slots["area"] == "望京 SOHO"
    assert "guangdong" in gate.extracted_slots["user_profile"]
    assert "light" in gate.extracted_slots["taste_preference"]


def test_haidilao_not_spicy_two_people_slots() -> None:
    gate = run_input_gate("我在三里屯海底捞，两个人不太能吃辣，帮我点")

    assert gate.decision_domain == "venue_ordering"
    assert gate.location_state == "in_venue"
    assert gate.route_priority == "venue_ordering"
    assert gate.extracted_slots["venue"] == "海底捞"
    assert gate.extracted_slots["area"] == "三里屯"
    assert gate.extracted_slots["party_size"] == 2
    assert gate.extracted_slots["spice_preference"] == "not_spicy"


def test_food_followup_inherits_previous_area_slots() -> None:
    gate = run_input_gate("我想吃川菜啊", latest_user_context="我在上海互联宝地")

    assert gate.decision_domain == "food"
    assert gate.location_state == "in_area"
    assert gate.route_priority == "area_food"
    assert gate.extracted_slots["city"] == "上海"
    assert gate.extracted_slots["area"] == "互联宝地"
    assert gate.extracted_slots["cuisine"] == "川菜"
    assert gate.extracted_slots["task"] == "choose_restaurant"
    assert gate.should_enter_loop is True
