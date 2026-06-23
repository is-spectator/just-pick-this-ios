from __future__ import annotations

import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import HelpCard, Question
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


FEEDBACK_TEXT = "预算不高，别太远，不要游客区，也想买美妆。"


async def _create_help_card_draft(client: AsyncClient, *, case_name: str) -> tuple[str, str]:
    boot = await bootstrap(
        client,
        device_id=f"pytest-update-help-card-{case_name}-{uuid.uuid4()}",
    )
    body = await chat_turn(
        client,
        conversation_id=boot["conversation_id"],
        message="在韩国逛街，不想去明洞，想小众，求一个。",
    )
    assert body["help_cards"], body
    return boot["conversation_id"], body["help_cards"][0]["id"]


async def _send_feedback(
    client: AsyncClient,
    *,
    conversation_id: str,
    help_card_id: str,
) -> dict[str, Any]:
    return await chat_turn(
        client,
        conversation_id=conversation_id,
        message=FEEDBACK_TEXT,
        metadata={"help_card_id": help_card_id},
    )


def _conversation_counts(conversation_id: str) -> dict[str, int]:
    conversation_uuid = uuid.UUID(conversation_id)
    with session_scope() as session:
        question_count = session.scalar(
            select(func.count()).select_from(Question).where(Question.conversation_id == conversation_uuid)
        )
        help_card_count = session.scalar(
            select(func.count()).select_from(HelpCard).where(HelpCard.conversation_id == conversation_uuid)
        )
    return {
        "questions": question_count or 0,
        "help_cards": help_card_count or 0,
    }


def _help_card_snapshot(help_card_id: str) -> dict[str, Any]:
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        assert help_card is not None
        return {
            "id": str(help_card.id),
            "title": help_card.title,
            "context_text": help_card.context_text,
            "payload_json": dict(help_card.payload_json or {}),
            "status": help_card.status,
        }


def _combined_help_card_text(snapshot: dict[str, Any]) -> str:
    return f"{snapshot['title']} {snapshot['context_text']} {json.dumps(snapshot['payload_json'], ensure_ascii=False)}"


def _archive_test_help_card(help_card_id: str | None) -> None:
    if help_card_id is None:
        return
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        if help_card is not None:
            help_card.status = "test_archived"


def test_update_help_card_from_user_feedback(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            conversation_id, help_card_id = await _create_help_card_draft(
                async_client,
                case_name="updates-card",
            )
            before = _help_card_snapshot(help_card_id)

            body = await _send_feedback(
                async_client,
                conversation_id=conversation_id,
                help_card_id=help_card_id,
            )

            update_calls = [
                tool
                for tool in body["tool_calls"]
                if tool.get("name") == "update_help_card"
            ]
            assert update_calls, body
            assert update_calls[-1]["status"] == "succeeded"

            after = _help_card_snapshot(help_card_id)
            assert after["id"] == before["id"]
            assert after != before
            combined_text = _combined_help_card_text(after)
            for keyword in ("预算", "别太远", "游客区", "美妆"):
                assert keyword in combined_text
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)


def test_update_help_card_does_not_create_new_help_card(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            conversation_id, help_card_id = await _create_help_card_draft(
                async_client,
                case_name="same-card",
            )
            before_counts = _conversation_counts(conversation_id)

            body = await _send_feedback(
                async_client,
                conversation_id=conversation_id,
                help_card_id=help_card_id,
            )

            assert any(tool.get("name") == "update_help_card" for tool in body["tool_calls"])
            after_counts = _conversation_counts(conversation_id)
            assert after_counts["help_cards"] == before_counts["help_cards"]
            assert body["help_cards"]
            assert body["help_cards"][0]["id"] == help_card_id
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)


def test_update_help_card_does_not_create_question(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            conversation_id, help_card_id = await _create_help_card_draft(
                async_client,
                case_name="no-question",
            )
            before_counts = _conversation_counts(conversation_id)

            body = await _send_feedback(
                async_client,
                conversation_id=conversation_id,
                help_card_id=help_card_id,
            )

            assert any(tool.get("name") == "update_help_card" for tool in body["tool_calls"])
            after_counts = _conversation_counts(conversation_id)
            assert after_counts["questions"] == before_counts["questions"]
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)
