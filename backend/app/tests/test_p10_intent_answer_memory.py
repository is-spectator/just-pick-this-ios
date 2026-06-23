from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import inspect, select

from app.models import HelpCard, IntentAnswer
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, require_ready_response


REQUIRED_INTENT_ANSWER_MEMORY_FIELDS = {
    "intent_key",
    "intent_text",
    "answer_title",
    "answer_summary",
    "constraints_json",
    "source_type",
    "source_ref_id",
    "confidence",
    "success_count",
    "rejection_count",
    "last_used_at",
}


async def _create_published_help_card(client: AsyncClient, *, case_name: str) -> str:
    owner = await bootstrap(
        client,
        device_id=f"pytest-intent-answer-memory-owner-{case_name}-{uuid.uuid4()}",
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


async def _submit_three_one_liners(client: AsyncClient, *, help_card_id: str, case_name: str) -> None:
    for index, text in enumerate(
        [
            "别去明洞，去圣水，店更小众。",
            "圣水适合女生逛品牌和美妆。",
            "预算不高也能在圣水慢慢逛。",
        ],
        start=1,
    ):
        response = await client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "user_id": f"pytest-intent-answer-memory-answerer-{case_name}-{index}-{uuid.uuid4()}",
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


def test_intent_answer_has_memory_fields() -> None:
    model_columns = {column.name for column in IntentAnswer.__table__.columns}
    missing_model_columns = REQUIRED_INTENT_ANSWER_MEMORY_FIELDS - model_columns
    assert not missing_model_columns, {
        "missing_model_columns": sorted(missing_model_columns),
        "model_columns": sorted(model_columns),
    }

    with session_scope() as session:
        inspector = inspect(session.bind)
        db_columns = {column["name"] for column in inspector.get_columns("intent_answers")}

    missing_db_columns = REQUIRED_INTENT_ANSWER_MEMORY_FIELDS - db_columns
    assert not missing_db_columns, {
        "missing_db_columns": sorted(missing_db_columns),
        "db_columns": sorted(db_columns),
    }


def test_finalizer_writes_help_final_intent_answer(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        help_card_id: str | None = None
        try:
            help_card_id = await _create_published_help_card(async_client, case_name="finalizer")
            await _submit_three_one_liners(
                async_client,
                help_card_id=help_card_id,
                case_name="finalizer",
            )

            with session_scope() as session:
                intent_answer = session.scalar(
                    select(IntentAnswer)
                    .where(
                        IntentAnswer.source_type == "help_final",
                        IntentAnswer.source_ref_id == help_card_id,
                    )
                    .order_by(IntentAnswer.created_at.desc())
                )

            assert intent_answer is not None
            assert intent_answer.intent_key
            assert intent_answer.intent_text
            assert intent_answer.answer_title
            assert intent_answer.answer_summary
            assert intent_answer.confidence is not None
            assert intent_answer.confidence > 0
            assert intent_answer.success_count == 0
            assert intent_answer.rejection_count == 0
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)
