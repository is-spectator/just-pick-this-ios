from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models import HelpCard, RetrievalHit
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, require_ready_response


def _retrieval_source_types(body: dict[str, Any]) -> set[str]:
    retrieval_run = body.get("metadata", {}).get("retrieval_run")
    assert retrieval_run is not None, body
    assert retrieval_run["id"], retrieval_run

    with session_scope() as session:
        return set(
            session.scalars(
                select(RetrievalHit.source_type).where(
                    RetrievalHit.retrieval_run_id == uuid.UUID(retrieval_run["id"])
                )
            )
        )


async def _run_datong_decision_request(client: AsyncClient, *, case_name: str) -> dict[str, Any]:
    boot = await bootstrap(
        client,
        device_id=f"pytest-layered-retrieval-datong-{case_name}-{uuid.uuid4()}",
    )
    return await chat_turn(
        client,
        conversation_id=boot["conversation_id"],
        message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
    )


async def _create_finalized_korea_help_card(
    client: AsyncClient,
    *,
    case_name: str,
) -> tuple[str, str]:
    owner = await bootstrap(
        client,
        device_id=f"pytest-layered-retrieval-korea-{case_name}-{uuid.uuid4()}",
    )
    draft = await chat_turn(
        client,
        conversation_id=owner["conversation_id"],
        message="在韩国逛街，不想去明洞，想小众，求一个。",
    )
    help_card_id = draft["help_cards"][0]["id"]
    await chat_turn(
        client,
        conversation_id=owner["conversation_id"],
        message="发出去",
        metadata={"help_card_id": help_card_id},
    )

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
                "user_id": f"pytest-layered-retrieval-answerer-{case_name}-{index}-{uuid.uuid4()}",
                "text": text,
            },
        )
        latest_body = require_ready_response(response)

    assert latest_body["metadata"]["finalization_ready"] is True
    assert latest_body["metadata"]["final_card_id"]
    return owner["conversation_id"], help_card_id


async def _run_korea_followup_decision_request(
    client: AsyncClient,
    *,
    conversation_id: str,
) -> dict[str, Any]:
    return await chat_turn(
        client,
        conversation_id=conversation_id,
        message="韩国逛街买什么，给我选一个。",
    )


def _archive_test_help_card(help_card_id: str | None) -> None:
    if help_card_id is None:
        return
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        if help_card is not None:
            help_card.status = "test_archived"


def test_retrieval_hits_include_intent_answer(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        body = await _run_datong_decision_request(async_client, case_name="intent-answer")

        assert "intent_answer" in _retrieval_source_types(body)

    run_async(scenario)


def test_retrieval_hits_include_image_asset(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        body = await _run_datong_decision_request(async_client, case_name="image-asset")

        assert "image_asset" in _retrieval_source_types(body)

    run_async(scenario)


def test_retrieval_hits_include_help_answer_when_available(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            conversation_id, help_card_id = await _create_finalized_korea_help_card(
                async_client,
                case_name="help-answer",
            )
            body = await _run_korea_followup_decision_request(
                async_client,
                conversation_id=conversation_id,
            )

            assert "help_answer" in _retrieval_source_types(body)
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)


def test_retrieval_hits_include_recommendation_card_when_available(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            conversation_id, help_card_id = await _create_finalized_korea_help_card(
                async_client,
                case_name="recommendation-card",
            )
            body = await _run_korea_followup_decision_request(
                async_client,
                conversation_id=conversation_id,
            )

            assert "recommendation_card" in _retrieval_source_types(body)
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)
