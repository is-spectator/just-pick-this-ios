from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import HelpCard, RecommendationCard
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


def _card_counts(conversation_id: str) -> dict[str, int]:
    conversation_uuid = uuid.UUID(conversation_id)
    with session_scope() as session:
        rec_count = session.scalar(
            select(func.count())
            .select_from(RecommendationCard)
            .where(RecommendationCard.conversation_id == conversation_uuid)
        )
        help_count = session.scalar(
            select(func.count()).select_from(HelpCard).where(HelpCard.conversation_id == conversation_uuid)
        )
    return {"recommendation_cards": int(rec_count or 0), "help_cards": int(help_count or 0)}


@pytest.mark.parametrize(
    "message",
    [
        "我想吃饭",
        "帮我选一家",
        "附近有什么好吃的",
        "帮我点菜",
        "我想吃火锅",
    ],
)
def test_ambiguous_request_clarifies_without_cards(
    run_async: Any,
    async_client: AsyncClient,
    message: str,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-clarification-no-card-{uuid.uuid4()}",
        )
        before = _card_counts(boot["conversation_id"])
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message=message,
        )
        after = _card_counts(boot["conversation_id"])

        assert body["response_kind"] == "clarification"
        assert body["ui_events"] == []
        assert body["data"]["clarification"]["missing_slots"]
        assert "help_card" not in body["data"]
        assert "recommendation_card" not in body["data"]
        assert after == before

    run_async(scenario)
