from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import UserBehaviorEvent
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, require_ready_response


def _event_count(**filters: Any) -> int:
    with session_scope() as session:
        query = select(func.count()).select_from(UserBehaviorEvent)
        for field, value in filters.items():
            column = getattr(UserBehaviorEvent, field)
            query = query.where(column == value)
        return int(session.scalar(query) or 0)


async def _draft_help_card(client: AsyncClient, *, device_id: str) -> tuple[str, str]:
    boot = await bootstrap(client, device_id=device_id)
    body = await chat_turn(
        client,
        conversation_id=boot["conversation_id"],
        message="韩国逛街，不去明洞，想小众",
    )
    help_cards = body.get("help_cards") or []
    assert help_cards, body
    return boot["conversation_id"], str(help_cards[0]["id"])


def test_recommendation_accept_writes_user_behavior_event(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-behavior-accept-{uuid.uuid4()}"
        boot = await bootstrap(async_client, device_id=device_id)
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        card_id = str(body["cards"][0]["id"])

        response = await async_client.post(
            f"/v1/cards/{card_id}/accept",
            json={"device_id": device_id, "metadata": {"surface": "chat_card"}},
        )
        accepted = require_ready_response(response)
        assert accepted["accepted"] is True
        assert _event_count(
            event_type="recommendation_card_accepted",
            recommendation_card_id=uuid.UUID(card_id),
        ) == 1

    run_async(scenario)


def test_help_publish_and_one_liner_write_user_behavior_events(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        owner_device = f"pytest-behavior-owner-{uuid.uuid4()}"
        _, help_card_id = await _draft_help_card(async_client, device_id=owner_device)

        publish = await async_client.post(
            f"/v1/help-cards/{help_card_id}/publish",
            json={"device_id": owner_device},
        )
        require_ready_response(publish)
        assert _event_count(event_type="help_card_published", help_card_id=uuid.UUID(help_card_id)) == 1

        answer = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "device_id": f"pytest-behavior-answer-{uuid.uuid4()}",
                "text": "别去明洞，去圣水更小众。",
            },
        )
        body = require_ready_response(answer)
        assert body["answer_id"]
        assert _event_count(event_type="one_liner_submitted", help_answer_id=uuid.UUID(body["answer_id"])) == 1

    run_async(scenario)


def test_generic_behavior_event_endpoint_records_ask_human(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-behavior-generic-{uuid.uuid4()}"
        boot = await bootstrap(async_client, device_id=device_id)
        response = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "conversation_id": boot["conversation_id"],
                "event_type": "ask_human_requested",
                "source": "ios",
                "metadata": {"surface": "recommendation_card"},
            },
        )
        body = require_ready_response(response)
        assert body["accepted"] is True
        assert body["event"]["event_type"] == "ask_human_requested"
        assert _event_count(
            event_type="ask_human_requested",
            conversation_id=uuid.UUID(boot["conversation_id"]),
        ) == 1

    run_async(scenario)
