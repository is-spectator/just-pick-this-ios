from __future__ import annotations

import pytest

ability_center_module = pytest.importorskip("app.ability.center", exc_type=ImportError)
registry_module = pytest.importorskip("app.ability.registry", exc_type=ImportError)
pipi_loop_module = pytest.importorskip("app.agent.pipi_loop", exc_type=ImportError)

AbilityCenter = ability_center_module.AbilityCenter
PipiState = pipi_loop_module.PipiState


def _ability_tools() -> dict[str, object]:
    if hasattr(registry_module, "ABILITY_TOOLS"):
        return dict(registry_module.ABILITY_TOOLS)
    if hasattr(registry_module, "build_default_registry"):
        return dict(registry_module.build_default_registry())
    pytest.fail("ability registry must expose ABILITY_TOOLS or build_default_registry")


@pytest.mark.asyncio
async def test_ability_center_rejects_unregistered_tool() -> None:
    result = await AbilityCenter({}).call(
        "missing_tool",
        {},
        state=PipiState(conversation_id="c", turn_id="t", user_message="x", allowed_tools=["missing_tool"]),
    )

    assert result.ok is False
    assert result.error_code == "tool_not_registered"
    assert "missing_tool" in (result.error_message or "")


@pytest.mark.asyncio
async def test_ability_center_enforces_allowed_tools() -> None:
    result = await AbilityCenter(_ability_tools()).call(
        "draft_help_card",
        {
            "title": "三里屯附近川菜求一个",
            "context": "三里屯附近想吃川菜",
        },
        state=PipiState(conversation_id="c", turn_id="t", user_message="x", allowed_tools=["search_knowledge"]),
    )

    assert result.ok is False
    assert result.status == "denied"
    assert result.error_code == "tool_not_allowed"


@pytest.mark.asyncio
async def test_ability_center_runs_allowed_tool() -> None:
    result = await AbilityCenter(_ability_tools()).call(
        "draft_help_card",
        {
            "question_id": "q",
            "owner_user_id": "u",
            "title": "三里屯附近川菜求一个",
            "context": "三里屯附近想吃川菜",
            "wants": ["川菜"],
            "avoids": ["太远"],
        },
        state=PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="x",
            allowed_tools=["draft_help_card"],
        ),
    )

    assert result.ok is True


@pytest.mark.asyncio
async def test_budget_followup_updates_same_help_card() -> None:
    result = await AbilityCenter(_ability_tools()).call(
        "update_help_card",
        {
            "help_card_id": "help-active",
            "context": "预算不高",
            "constraints": {"budget": "not_high"},
        },
        state=PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="预算不高",
            allowed_tools=["update_help_card"],
            metadata={
                "user_id": "u",
                "help_card": {
                    "help_card_id": "help-active",
                    "question_id": "q",
                    "owner_user_id": "u",
                    "title": "三里屯附近川菜求一个",
                    "context": "三里屯附近想吃川菜",
                    "wants": ["川菜"],
                    "avoids": ["太远"],
                    "constraints": {},
                    "revision": 1,
                    "status": "draft",
                    "answer_count": 0,
                    "min_answers_required": 3,
                },
            },
        ),
    )

    assert result.ok is True
    assert result.output is not None
    assert result.output["help_card_id"] == "help-active"
    assert result.output["context"] == "预算不高"
    assert result.output["constraints"] == {"budget": "not_high"}


@pytest.mark.asyncio
async def test_recommendation_card_requires_evidence() -> None:
    result = await AbilityCenter(_ability_tools()).call(
        "create_recommendation_card",
        {
            "question_id": "q",
            "item": {"title": "刀削面 + 肉丸子"},
            "decision_factor": {"text": "第一次来大同，地方记忆点最强。"},
            "confidence": 0.8,
        },
        state=PipiState(
            conversation_id="c",
            turn_id="t",
            user_message="x",
            allowed_tools=["create_recommendation_card"],
        ),
    )

    assert result.ok is False
    assert result.error_code == "precondition_failed"
    assert "requires evidence" in (result.error_message or "")


def test_registry_includes_finalize_graph_tool_boundary() -> None:
    assert "finalize_help_card" in _ability_tools()
