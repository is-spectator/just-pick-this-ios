from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models import AgentRun, HelpCard, ToolCall
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, require_ready_response


EXPECTED_FINALIZE_TOOL_NAMES = {
    "finalize_help_card",
    "create_recommendation_card",
    "save_intent_answer",
    "light_user",
}

DEPRECATED_FINALIZE_TOOL_NAMES = {
    "finalize_recommendation",
    "create_final_recommendation_card",
}


async def _create_published_help_card(client: AsyncClient) -> str:
    owner = await bootstrap(
        client,
        device_id=f"pytest-finalize-tool-chain-owner-{uuid.uuid4()}",
    )
    draft = await chat_turn(
        client,
        conversation_id=owner["conversation_id"],
        message="在韩国逛街，不想去明洞，想小众，求一个。",
    )
    help_card_id = draft["help_cards"][0]["id"]
    published = await chat_turn(
        client,
        conversation_id=owner["conversation_id"],
        message="发出去",
        metadata={"help_card_id": help_card_id},
    )
    assert published["help_cards"], published
    return help_card_id


async def _submit_three_one_liners(client: AsyncClient, *, help_card_id: str) -> None:
    for index, text in enumerate(
        [
            "别去明洞当背景板，去圣水。",
            "圣水咖啡和小店密度高。",
            "预算不高也能逛圣水。",
        ],
        start=1,
    ):
        response = await client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "user_id": f"pytest-finalize-tool-chain-answerer-{index}-{uuid.uuid4()}",
                "text": text,
            },
        )
        body = require_ready_response(response)
    assert body["metadata"]["finalization_ready"] is True
    assert body["metadata"]["final_card_id"]


def _archive_test_help_card(help_card_id: str | None) -> None:
    if help_card_id is None:
        return
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        if help_card is not None:
            help_card.status = "test_archived"


def _finalize_tool_names_for_help_card(help_card_id: str) -> list[str]:
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        assert help_card is not None
        finalizer_run_ids = list(
            session.scalars(
                select(AgentRun.id).where(
                    AgentRun.conversation_id == help_card.conversation_id,
                    AgentRun.run_type == "pipi_finalize",
                    AgentRun.graph_name == "PipiFinalizeGraph",
                )
            )
        )
        assert finalizer_run_ids, "one-liner threshold should create a PipiFinalizeGraph AgentRun"
        return list(
            session.scalars(
                select(ToolCall.tool_name)
                .where(ToolCall.agent_run_id.in_(finalizer_run_ids))
                .order_by(ToolCall.sequence_index.asc(), ToolCall.created_at.asc())
            )
        )


def test_finalize_tool_chain_records_expected_tool_calls(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            help_card_id = await _create_published_help_card(async_client)
            await _submit_three_one_liners(async_client, help_card_id=help_card_id)

            tool_names = _finalize_tool_names_for_help_card(help_card_id)
            tool_name_set = set(tool_names)
            missing_standard_names = EXPECTED_FINALIZE_TOOL_NAMES - tool_name_set
            deprecated_names = DEPRECATED_FINALIZE_TOOL_NAMES & tool_name_set

            assert not missing_standard_names, {
                "missing_standard_tool_names": sorted(missing_standard_names),
                "recorded_tool_names": tool_names,
            }
            assert not deprecated_names, {
                "deprecated_tool_names": sorted(deprecated_names),
                "recorded_tool_names": tool_names,
            }
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)
