from __future__ import annotations

from app.harness.input_gate import run_input_gate


def test_greeting_never_enters_loop() -> None:
    gate = run_input_gate("你好")

    assert gate.intent_type == "greeting"
    assert gate.should_enter_loop is False
    assert gate.should_create_question is False
    assert gate.should_retrieve is False
    assert gate.allowed_tools == []


def test_who_are_you_never_enters_loop() -> None:
    gate = run_input_gate("你是谁")

    assert gate.intent_type == "smalltalk"
    assert gate.should_enter_loop is False
    assert gate.should_create_question is False
    assert gate.should_retrieve is False
    assert gate.allowed_tools == []


def test_app_help_never_enters_loop() -> None:
    gate = run_input_gate("这个 app 怎么用？")

    assert gate.intent_type == "app_help"
    assert gate.should_enter_loop is False
    assert gate.should_create_question is False
    assert gate.allowed_tools == []


def test_unknown_never_creates_question() -> None:
    gate = run_input_gate("随便啦")

    assert gate.intent_type == "unknown"
    assert gate.should_enter_loop is False
    assert gate.should_create_question is False
    assert gate.should_retrieve is False
    assert gate.allowed_tools == []


def test_decision_request_enters_loop_with_narrow_tools() -> None:
    gate = run_input_gate("我在大同喜晋道，吃什么")

    assert gate.intent_type == "decision_request"
    assert gate.should_enter_loop is True
    assert gate.should_create_question is True
    assert gate.should_retrieve is True
    assert gate.allowed_tools == ["search_knowledge", "create_recommendation_card", "draft_help_card"]


def test_publish_without_active_help_card_does_not_call_tool() -> None:
    gate = run_input_gate("发出去")

    assert gate.intent_type == "publish_help"
    assert gate.should_enter_loop is False
    assert gate.allowed_tools == []


def test_publish_with_active_help_card_can_call_publish_tool() -> None:
    gate = run_input_gate("发出去", active_help_card_id="help-card-id")

    assert gate.intent_type == "publish_help"
    assert gate.should_enter_loop is True
    assert gate.should_create_question is False
    assert gate.should_retrieve is False
    assert gate.allowed_tools == ["publish_help_card"]


def test_active_help_followup_can_update_card() -> None:
    gate = run_input_gate("可是有哪些肉店呢", active_help_card_id="help-card-id")

    assert gate.intent_type == "update_help_card"
    assert gate.should_enter_loop is True
    assert gate.allowed_tools == ["update_help_card"]
