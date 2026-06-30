from __future__ import annotations

from app.services.chat import _chat_response_contract


def test_app_help_input_gate_result_is_chitchat_contract() -> None:
    contract = _chat_response_contract(
        payload={"message": "怎么用"},
        state={
            "intent": "app_help",
            "metadata": {
                "input_gate_result": {
                    "intent_type": "app_help",
                    "decision_domain": "chitchat",
                    "should_enter_loop": False,
                }
            },
        },
        cards=[],
        help_cards=[],
        retrieval_run=None,
        agent_run_id="agent-run-test",
        tool_calls=[],
    )

    assert contract["response_kind"] == "chitchat"
    assert contract["location_state"] == "unknown"
    assert contract["data"] == {}
