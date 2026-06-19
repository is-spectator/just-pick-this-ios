from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import (
    AgentRun,
    HelpCard,
    Question,
    RecommendationCard,
    RetrievalRun,
    ToolCall,
    Turn,
)
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


def _fresh_device_id(case_name: str) -> str:
    return f"pytest-p0-{case_name}-{uuid.uuid4()}"


def _conversation_state_counts(conversation_id: str) -> dict[str, Any]:
    conversation_uuid = uuid.UUID(conversation_id)
    with session_scope() as session:
        turn_roles = list(
            session.scalars(
                select(Turn.role)
                .where(Turn.conversation_id == conversation_uuid)
                .order_by(Turn.turn_index)
            )
        )
        question_count = session.scalar(
            select(func.count()).select_from(Question).where(Question.conversation_id == conversation_uuid)
        )
        tool_call_count = session.scalar(
            select(func.count())
            .select_from(ToolCall)
            .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_uuid)
        )
        retrieval_run_count = session.scalar(
            select(func.count())
            .select_from(RetrievalRun)
            .join(AgentRun, RetrievalRun.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_uuid)
        )
        recommendation_card_count = session.scalar(
            select(func.count())
            .select_from(RecommendationCard)
            .where(RecommendationCard.conversation_id == conversation_uuid)
        )
        help_card_count = session.scalar(
            select(func.count()).select_from(HelpCard).where(HelpCard.conversation_id == conversation_uuid)
        )

    return {
        "turn_roles": turn_roles,
        "question_count": question_count or 0,
        "tool_call_count": tool_call_count or 0,
        "retrieval_run_count": retrieval_run_count or 0,
        "recommendation_card_count": recommendation_card_count or 0,
        "help_card_count": help_card_count or 0,
    }


async def _assert_non_decision_turn_only_persists_turns(
    client: AsyncClient,
    *,
    case_name: str,
    message: str,
) -> None:
    boot = await bootstrap(client, device_id=_fresh_device_id(case_name))
    body = await chat_turn(
        client,
        conversation_id=boot["conversation_id"],
        message=message,
    )

    assert body["cards"] == []
    assert body["help_cards"] == []
    assert body["tool_calls"] == []
    assert body.get("metadata", {}).get("retrieval_run") is None

    counts = _conversation_state_counts(boot["conversation_id"])
    assert counts["turn_roles"] == ["user", "assistant"]
    assert counts["question_count"] == 0
    assert counts["tool_call_count"] == 0
    assert counts["retrieval_run_count"] == 0
    assert counts["recommendation_card_count"] == 0
    assert counts["help_card_count"] == 0


def test_greeting_does_not_create_question(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        await _assert_non_decision_turn_only_persists_turns(
            async_client,
            case_name="greeting",
            message="你好",
        )

    run_async(scenario)


def test_smalltalk_does_not_create_question(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        await _assert_non_decision_turn_only_persists_turns(
            async_client,
            case_name="smalltalk",
            message="哈哈",
        )

    run_async(scenario)


def test_app_help_does_not_create_question(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        await _assert_non_decision_turn_only_persists_turns(
            async_client,
            case_name="app-help",
            message="这个 app 怎么用？",
        )

    run_async(scenario)


def test_unknown_does_not_create_question(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        await _assert_non_decision_turn_only_persists_turns(
            async_client,
            case_name="unknown",
            message="蓝色月亮今天会唱歌吗？",
        )

    run_async(scenario)


def test_decision_request_still_creates_question(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id=_fresh_device_id("decision"))
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        assert body["conversation_id"] == boot["conversation_id"]
        counts = _conversation_state_counts(boot["conversation_id"])
        assert counts["turn_roles"] == ["user", "assistant"]
        assert counts["question_count"] == 1

    run_async(scenario)
