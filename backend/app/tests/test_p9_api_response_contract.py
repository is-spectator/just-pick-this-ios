from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from .conftest import bootstrap, chat_turn


async def _run_datong_chat_turn(client: AsyncClient, *, case_name: str) -> dict[str, Any]:
    boot = await bootstrap(
        client,
        device_id=f"pytest-api-contract-{case_name}-{uuid.uuid4()}",
    )
    return await chat_turn(
        client,
        conversation_id=boot["conversation_id"],
        message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
    )


def test_chat_turn_response_has_top_level_ui_events(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        body = await _run_datong_chat_turn(async_client, case_name="ui-events")

        assert body["conversation_id"]
        assert "turn_id" in body
        assert body["turn_id"]
        assert body["assistant_message"]
        assert "ui_events" in body
        assert isinstance(body["ui_events"], list)
        assert body["ui_events"], body
        assert "ui_events" not in body.get("metadata", {})

    run_async(scenario)


def test_chat_turn_response_has_metadata_intent_agent_run_retrieval_run(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        body = await _run_datong_chat_turn(async_client, case_name="metadata")
        metadata = body.get("metadata")

        assert isinstance(metadata, dict), body
        assert isinstance(metadata.get("intent"), dict)
        assert metadata["intent"].get("name") or metadata["intent"].get("value") or metadata["intent"].get("type")
        assert metadata.get("agent_run_id")
        assert metadata.get("retrieval_run_id")

        retrieval_run = metadata.get("retrieval_run")
        assert isinstance(retrieval_run, dict)
        assert retrieval_run.get("id") == metadata["retrieval_run_id"]

    run_async(scenario)
