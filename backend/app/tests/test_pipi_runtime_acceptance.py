from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models import IntentAnswer, RetrievalHit, RetrievalRun, ToolCall
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, extract_tool_names, require_ready_response


async def _create_published_help_card(
    client: AsyncClient,
    *,
    device_id: str,
    user_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    owner = await bootstrap(client, device_id=device_id, user_id=user_id)
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
    assert "publish_help_card" in extract_tool_names(published)
    return owner, help_card_id


def test_bootstrap_deduplicates_by_device_id(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        first = await bootstrap(async_client, device_id="pytest-bootstrap-dedupe")
        second = await bootstrap(async_client, device_id="pytest-bootstrap-dedupe")

        assert first["conversation_id"]
        assert second["conversation_id"]
        assert first.get("user_id") == second.get("user_id")

    run_async(scenario)


def test_chat_turn_recovers_from_unknown_client_conversation_id(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        stale_conversation_id = "11111111-1111-4111-8111-111111111111"
        body = await chat_turn(
            async_client,
            conversation_id=stale_conversation_id,
            message="我在哪，随便求一个。",
        )

        assert body["conversation_id"] != stale_conversation_id
        assert body["user_turn_id"]

    run_async(scenario)


def test_greeting_does_not_create_card_help_or_tool(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-hello-no-tool")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="你好",
        )

        assert body["cards"] == []
        assert body["help_cards"] == []
        assert body["tool_calls"] == []

    run_async(scenario)


def test_identity_question_does_not_return_recommendation_card(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-who-are-you")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="你是谁？",
        )

        assert body["cards"] == []
        assert body["help_cards"] == []

    run_async(scenario)


def test_datong_question_returns_recommendation_card_via_tool_call(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-datong-card")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，就选一个。",
        )

        assert body["conversation_id"] == boot["conversation_id"]
        assert "create_recommendation_card" in extract_tool_names(body)
        assert body["cards"], body
        card = body["cards"][0]
        searchable_text = f"{card.get('title', '')} {card.get('subtitle', '')} {card.get('one_liner', '')}"
        assert "大同" in searchable_text or "喜晋道" in searchable_text

    run_async(scenario)


def test_recommendation_cards_require_verified_non_ai_images(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-image-constraints")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        assert body["cards"], body
        for card in body["cards"]:
            image = card.get("image")
            assert image is not None, card
            assert image["verified"] is True
            assert image["is_ai_generated"] is False

    run_async(scenario)


def test_korea_shopping_question_creates_help_draft(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-korea-help-draft")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )

        assert "draft_help_card" in extract_tool_names(body)
        assert body["help_cards"], body
        help_card = body["help_cards"][0]
        assert help_card["status"] in {"draft", "open"}
        assert help_card.get("card") is None

    run_async(scenario)


def test_korea_shopping_question_with_recommend_word_still_creates_help_draft(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-korea-recommend-help")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，给我推荐一个。",
        )

        assert "draft_help_card" in extract_tool_names(body)
        assert body["cards"] == []
        assert body["help_cards"], body

    run_async(scenario)


def test_publish_help_draft_enters_help_feed(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        no_active = await bootstrap(async_client, device_id="pytest-publish-no-active")
        skipped = await chat_turn(
            async_client,
            conversation_id=no_active["conversation_id"],
            message="发出去",
        )
        publish_calls = [
            tool for tool in skipped["tool_calls"] if tool.get("name") == "publish_help_card"
        ]
        if publish_calls:
            assert publish_calls[0]["status"] == "skipped"
        assert skipped["help_cards"] == []

        owner = await bootstrap(async_client, device_id="pytest-publish-owner", user_id="pytest-owner")
        draft = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        help_card_id = draft["help_cards"][0]["id"]

        published = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="发出去",
            metadata={"help_card_id": help_card_id},
        )
        assert "publish_help_card" in extract_tool_names(published)

        response = await async_client.get(
            "/v1/help-feed",
            params={"user_id": "pytest-answerer-feed", "limit": 100},
        )
        feed = require_ready_response(response)
        assert help_card_id in {item["id"] for item in feed["items"]}

    run_async(scenario)


def test_help_feed_excludes_cards_owned_by_requesting_user(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        owner = await bootstrap(async_client, device_id="pytest-feed-owner", user_id="pytest-feed-owner")
        draft = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        help_card_id = draft["help_cards"][0]["id"]
        await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="发出去",
            metadata={"help_card_id": help_card_id},
        )

        response = await async_client.get(
            "/v1/help-feed",
            params={"user_id": "pytest-feed-owner", "limit": 10},
        )
        feed = require_ready_response(response)
        assert help_card_id not in {item["id"] for item in feed["items"]}

    run_async(scenario)


def test_owner_cannot_answer_own_help_card(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        _, help_card_id = await _create_published_help_card(
            async_client,
            device_id="pytest-owner-answer",
            user_id="pytest-owner-answer",
        )

        response = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"user_id": "pytest-owner-answer", "text": "别去明洞，去圣水。"},
        )
        require_ready_response(response, expected_status=403)

    run_async(scenario)


def test_other_user_can_submit_one_liner_as_human_evidence(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        _, help_card_id = await _create_published_help_card(
            async_client,
            device_id="pytest-one-liner-owner",
        )

        response = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"user_id": "pytest-answerer-1", "text": "别去明洞，去圣水。"},
        )
        body = require_ready_response(response)
        assert body["help_card_id"] == help_card_id
        assert body["accepted"] is True
        assert body["answer_id"]
        assert body.get("metadata", {}).get("evidence_type") in {None, "human_one_liner"}

    run_async(scenario)


def test_three_help_answers_finalize_recommendation_card(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        _, help_card_id = await _create_published_help_card(
            async_client,
            device_id="pytest-finalize-owner",
        )

        for index, text in enumerate(
            [
                "别去明洞当背景板，去圣水。",
                "圣水咖啡和小店密度高。",
                "预算不高也能逛圣水。",
            ],
            start=1,
        ):
            response = await async_client.post(
                f"/v1/help-cards/{help_card_id}/one-liner",
                json={"user_id": f"pytest-final-answerer-{index}", "text": text},
            )
            answer_body = require_ready_response(response)

        metadata = answer_body.get("metadata", {})
        assert metadata.get("answer_count") == 3
        assert metadata.get("finalization_ready") is True
        assert metadata.get("final_card_id")

        response = await async_client.get(
            f"/v1/cards/{metadata['final_card_id']}",
        )
        card = require_ready_response(response)
        assert card["id"] == metadata["final_card_id"]
        assert "圣水" in f"{card.get('title', '')} {card.get('subtitle', '')}"

    run_async(scenario)


def test_final_recommendation_writes_intent_answer(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        _, help_card_id = await _create_published_help_card(
            async_client,
            device_id="pytest-final-intent-answer",
        )

        for index in range(1, 4):
            response = await async_client.post(
                f"/v1/help-cards/{help_card_id}/one-liner",
                json={"user_id": f"pytest-final-intent-answerer-{index}", "text": f"圣水更适合 {index}"},
            )
            require_ready_response(response)

        with session_scope() as session:
            intent_answer_evidence = [
                dict(answer.evidence_json)
                for answer in session.scalars(select(IntentAnswer))
                if answer.evidence_json.get("help_card_id") == help_card_id
            ]

        assert intent_answer_evidence
        assert intent_answer_evidence[-1].get("source_type") == "help_final"

    run_async(scenario)


def test_finalization_writes_light_event(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        owner, help_card_id = await _create_published_help_card(
            async_client,
            device_id="pytest-light-event-owner",
        )

        for index in range(1, 4):
            response = await async_client.post(
                f"/v1/help-cards/{help_card_id}/one-liner",
                json={"user_id": f"pytest-light-answerer-{index}", "text": f"圣水更适合小众逛街 {index}"},
            )
            require_ready_response(response)

        finalized = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="最终答案",
            metadata={"help_card_id": help_card_id},
        )
        assert any(event.get("kind") == "final_ready" for event in finalized["light_events"])

        response = await async_client.get(
            "/v1/light-events",
            params={"user_id": owner.get("user_id"), "limit": 20},
        )
        events = require_ready_response(response)
        assert any(event.get("kind") == "final_ready" for event in events["items"])

    run_async(scenario)


def test_chat_turn_records_tool_calls_retrieval_run_and_hits(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-observability")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        assert body["tool_calls"], body
        for tool_call in body["tool_calls"]:
            assert tool_call.get("id")
            assert tool_call.get("status") in {"pending", "succeeded", "failed", "skipped", "unavailable"}

        metadata = body.get("metadata", {})
        retrieval_run = metadata.get("retrieval_run")
        assert retrieval_run is not None, body
        assert retrieval_run["id"]
        assert retrieval_run.get("status") in {"persisted", "succeeded"}
        assert retrieval_run.get("hits"), retrieval_run
        for hit in retrieval_run["hits"]:
            assert hit["id"]
            assert hit.get("score") is not None
            assert hit.get("source_id") or hit.get("image_asset_id") or hit.get("evidence_id")

        with session_scope() as session:
            tool_ids = [uuid.UUID(tool["id"]) for tool in body["tool_calls"]]
            persisted_tools = list(
                session.scalars(select(ToolCall).where(ToolCall.id.in_(tool_ids)))
            )
            persisted_run = session.get(RetrievalRun, uuid.UUID(retrieval_run["id"]))
            persisted_hits = list(
                session.scalars(
                    select(RetrievalHit).where(
                        RetrievalHit.retrieval_run_id == uuid.UUID(retrieval_run["id"])
                    )
                )
            )

        assert len(persisted_tools) == len(tool_ids)
        assert persisted_run is not None
        assert persisted_hits

    run_async(scenario)
