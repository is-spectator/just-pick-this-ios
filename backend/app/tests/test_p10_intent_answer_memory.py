from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import inspect, select

from app.models import HelpCard, IntentAnswer, RecommendationCard
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


def _intent_answer_for_card(card_id: str) -> IntentAnswer:
    with session_scope() as session:
        card = session.get(RecommendationCard, uuid.UUID(card_id))
        assert card is not None
        payload = card.payload_json or {}
        intent_answer_id = payload.get("intent_answer_id") or payload.get("reference_intent_answer_id")
        if not intent_answer_id:
            intent_answer_id = (payload.get("provenance") or {}).get("source_answer_id")
        assert intent_answer_id
        answer = session.get(IntentAnswer, uuid.UUID(str(intent_answer_id)))
        assert answer is not None
        session.expunge(answer)
        return answer


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


def test_accept_card_updates_intent_answer_success_memory(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-intent-memory-success-{uuid.uuid4()}"
        owner = await bootstrap(
            async_client,
            device_id=device_id,
        )
        body = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        card_id = body["cards"][0]["id"]
        before = _intent_answer_for_card(card_id)

        accepted = await async_client.post(
            f"/v1/cards/{card_id}/accept",
            json={"device_id": device_id},
        )
        require_ready_response(accepted)

        after = _intent_answer_for_card(card_id)
        assert after.success_count == before.success_count + 1
        assert after.rejection_count == before.rejection_count
        assert after.last_used_at is not None

        duplicate = await async_client.post(
            f"/v1/cards/{card_id}/accept",
            json={"device_id": device_id},
        )
        require_ready_response(duplicate)
        deduped = _intent_answer_for_card(card_id)
        assert deduped.success_count == after.success_count

    run_async(scenario)


def test_card_rejection_event_updates_intent_answer_rejection_memory(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-intent-memory-reject-{uuid.uuid4()}"
        owner = await bootstrap(
            async_client,
            device_id=device_id,
        )
        body = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        card_id = body["cards"][0]["id"]
        before = _intent_answer_for_card(card_id)

        event = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "conversation_id": owner["conversation_id"],
                "card_id": card_id,
                "event_type": "recommendation_card_changed",
                "source": "pytest",
            },
        )
        require_ready_response(event)

        after = _intent_answer_for_card(card_id)
        assert after.success_count == before.success_count
        assert after.rejection_count == before.rejection_count + 1

    run_async(scenario)


def test_post_experience_review_updates_intent_answer_memory(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-intent-memory-post-review-{uuid.uuid4()}"
        owner = await bootstrap(
            async_client,
            device_id=device_id,
        )
        body = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        card_id = body["cards"][0]["id"]
        before = _intent_answer_for_card(card_id)

        satisfied = await async_client.post(
            f"/v1/cards/{card_id}/review",
            json={
                "device_id": device_id,
                "outcome": "went_satisfied",
                "notes": "去了，确实稳。",
            },
        )
        satisfied_body = require_ready_response(satisfied)
        assert satisfied_body["accepted"] is True
        assert satisfied_body["event"]["event_type"] == "recommendation_card_post_review_satisfied"

        after_satisfied = _intent_answer_for_card(card_id)
        assert after_satisfied.success_count == before.success_count + 1
        assert after_satisfied.rejection_count == before.rejection_count

        regretted = await async_client.post(
            f"/v1/cards/{card_id}/review",
            json={
                "device_id": device_id,
                "outcome": "went_regretted",
                "notes": "去了，但不太满意。",
            },
        )
        regretted_body = require_ready_response(regretted)
        assert regretted_body["accepted"] is False
        assert regretted_body["event"]["event_type"] == "recommendation_card_post_review_regretted"

        after_regretted = _intent_answer_for_card(card_id)
        assert after_regretted.success_count == after_satisfied.success_count
        assert after_regretted.rejection_count == after_satisfied.rejection_count + 1

    run_async(scenario)
