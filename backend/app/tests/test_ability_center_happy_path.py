from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.ability.center import AbilityCenter
from app.ability.registry import build_default_registry
from app.ability.schemas import AbilityContext, AbilityTool
from app.tools.tool_call_logger import MemoryToolCallLogger


class _DraftArgs(BaseModel):
    question_id: str = Field(min_length=1)
    title: str = Field(min_length=1)


@pytest.mark.asyncio
async def test_ability_center_persists_one_tool_call_for_success() -> None:
    async def handler(context: AbilityContext, input_data: _DraftArgs) -> dict[str, Any]:
        nested_record = await context.tool_call_logger.start_tool_call(
            tool_name="draft_help_card",
            input_json=input_data.model_dump(mode="json"),
            agent_run_id=context.agent_run_id,
            question_id=input_data.question_id,
        )
        await context.tool_call_logger.finish_tool_call(
            tool_call_id=nested_record.id,
            status="succeeded",
            output_json={"ignored": True},
        )
        return {"nested_tool_call_id": nested_record.id}

    logger = MemoryToolCallLogger()
    result = await AbilityCenter(
        [
            AbilityTool(
                name="draft_help_card",
                input_schema=_DraftArgs,
                handler=handler,
            )
        ]
    ).execute(
        "draft_help_card",
        {"question_id": "q1", "title": "三里屯附近川菜求一个"},
        context=AbilityContext(
            agent_run_id="agent-1",
            allowed_tools=["draft_help_card"],
            tool_call_logger=logger,
        ),
    )

    assert result.ok is True
    assert len(logger.records) == 1
    record = logger.records[0]
    assert record.status == "succeeded"
    assert result.metadata["tool_call_id"] == record.id
    assert result.output == {"nested_tool_call_id": record.id}


@pytest.mark.asyncio
async def test_ability_center_persists_schema_failure_as_failed() -> None:
    logger = MemoryToolCallLogger()
    result = await AbilityCenter(
        [
            AbilityTool(
                name="draft_help_card",
                input_schema=_DraftArgs,
                handler=lambda _context, _input: {"unexpected": True},
            )
        ]
    ).execute(
        "draft_help_card",
        {"question_id": "q1"},
        context=AbilityContext(
            agent_run_id="agent-1",
            allowed_tools=["draft_help_card"],
            tool_call_logger=logger,
        ),
    )

    assert result.ok is False
    assert result.status == "failed"
    assert result.error_code == "schema_validation_error"
    assert len(logger.records) == 1
    assert logger.records[0].status == "failed"
    assert logger.records[0].error_message


@pytest.mark.asyncio
async def test_ability_center_persists_allowed_tools_denial_as_failed_tool_call() -> None:
    logger = MemoryToolCallLogger()
    result = await AbilityCenter(
        [
            AbilityTool(
                name="draft_help_card",
                input_schema=_DraftArgs,
                handler=lambda _context, _input: {"unexpected": True},
            )
        ]
    ).execute(
        "draft_help_card",
        {"question_id": "q1", "title": "三里屯附近川菜求一个"},
        context=AbilityContext(
            agent_run_id="agent-1",
            allowed_tools=["search_knowledge"],
            tool_call_logger=logger,
        ),
    )

    assert result.ok is False
    assert result.status == "denied"
    assert result.error_code == "tool_not_allowed"
    assert len(logger.records) == 1
    assert logger.records[0].status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["reasons", "bullets", "followups"])
async def test_create_recommendation_card_rejects_display_only_fields(field_name: str) -> None:
    result = await _call_create_recommendation_card({field_name: ["别把展示字段塞进工具参数"]})

    assert result.ok is False
    assert result.status == "failed"
    assert result.error_code == "precondition_failed"
    assert field_name in (result.error_message or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"decision_factors": [{"text": "地方记忆点强"}, {"text": "离你近"}]},
        {"decision_factor": [{"text": "地方记忆点强"}, {"text": "离你近"}]},
    ],
)
async def test_create_recommendation_card_rejects_multiple_decision_factors(
    override: dict[str, Any],
) -> None:
    result = await _call_create_recommendation_card(override)

    assert result.ok is False
    assert result.status == "failed"
    assert result.error_code == "precondition_failed"
    assert "one decision_factor" in (result.error_message or "")


@pytest.mark.asyncio
async def test_create_recommendation_card_persists_missing_evidence_failure() -> None:
    logger = MemoryToolCallLogger()
    result = await _call_create_recommendation_card({"evidence_ids": []}, logger=logger)

    assert result.ok is False
    assert result.status == "failed"
    assert result.error_code == "precondition_failed"
    assert "requires evidence" in (result.error_message or "")
    assert len(logger.records) == 1
    assert logger.records[0].status == "failed"


@pytest.mark.asyncio
async def test_update_help_card_uses_requested_help_card_snapshot() -> None:
    result = await AbilityCenter(build_default_registry()).execute(
        "update_help_card",
        {
            "help_card_id": "help-target",
            "context": "预算不高",
            "constraints": {"budget": "not_high"},
        },
        context=AbilityContext(
            allowed_tools=["update_help_card"],
            metadata={
                "help_card": {
                    "help_card_id": "help-other",
                    "question_id": "q-other",
                    "owner_user_id": "u-other",
                    "title": "别的求一个",
                    "context": "别的上下文",
                },
                "help_cards": {
                    "help-target": {
                        "help_card_id": "help-target",
                        "question_id": "q-target",
                        "owner_user_id": "u-target",
                        "title": "三里屯附近川菜求一个",
                        "context": "三里屯附近想吃川菜",
                        "constraints": {},
                    },
                },
            },
        ),
    )

    assert result.ok is True
    assert result.output is not None
    assert result.output["help_card_id"] == "help-target"
    assert result.output["question_id"] == "q-target"
    assert result.output["owner_user_id"] == "u-target"
    assert result.output["constraints"] == {"budget": "not_high"}


async def _call_create_recommendation_card(
    override: dict[str, Any],
    *,
    logger: MemoryToolCallLogger | None = None,
) -> Any:
    payload: dict[str, Any] = {
        "question_id": "q1",
        "item": {"title": "刀削面 + 肉丸子"},
        "decision_factor": {"text": "第一次来大同，地方记忆点最强。"},
        "image_asset_id": "img-datong",
        "evidence_ids": ["hit-datong"],
        "confidence": 0.8,
        **override,
    }
    return await AbilityCenter(build_default_registry()).execute(
        "create_recommendation_card",
        payload,
        context=AbilityContext(
            agent_run_id="agent-1" if logger is not None else None,
            allowed_tools=["create_recommendation_card"],
            tool_call_logger=logger,
            metadata={
                "verified_image_asset_ids": ["img-datong"],
                "retrieval_hits": [
                    {
                        "id": "hit-datong",
                        "source_id": "hit-datong",
                        "image_asset_id": "img-datong",
                    }
                ],
            },
        ),
    )
