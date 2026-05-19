from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from .conftest import bootstrap, chat_turn, extract_tool_names, require_ready_response


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

        assert "create_help_card" in extract_tool_names(body)
        assert body["help_cards"], body
        help_card = body["help_cards"][0]
        assert help_card["status"] in {"draft", "open"}
        assert help_card.get("card") is None

    run_async(scenario)


def test_korea_shopping_question_uses_reference_answer_as_evidence_not_final_copy(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-korea-reference-composed")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="在韩国逛街，不想去明洞",
        )

        assert "create_recommendation_card" in extract_tool_names(body)
        assert body["cards"], body
        card = body["cards"][0]
        assert "圣水" in f"{card.get('title', '')} {card.get('subtitle', '')}"
        assert card.get("one_liner") != "选圣水洞，适合直接逛街、看店、喝咖啡。"
        assert card.get("bullets"), card
        assert card.get("metadata", {}).get("composer", {}).get("composition") in {
            "reference_answer_adapted",
            "deepseek_reference_adapted",
        }

    run_async(scenario)


def test_publish_help_draft_enters_help_feed(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
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
        owner = await bootstrap(async_client, device_id="pytest-owner-answer", user_id="pytest-owner-answer")
        draft = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        help_card_id = draft["help_cards"][0]["id"]

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
        owner = await bootstrap(async_client, device_id="pytest-one-liner-owner")
        draft = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        help_card_id = draft["help_cards"][0]["id"]

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
        owner = await bootstrap(async_client, device_id="pytest-finalize-owner")
        draft = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        help_card_id = draft["help_cards"][0]["id"]

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

        finalized = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="最终答案",
            metadata={"help_card_id": help_card_id},
        )
        assert "finalize_recommendation" in extract_tool_names(finalized)
        assert finalized["cards"], finalized

    run_async(scenario)


def test_chat_turn_persists_intent_answer(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(async_client, device_id="pytest-intent-answer")
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么。",
        )

        intent_answer = body.get("metadata", {}).get("intent_answer")
        assert intent_answer is not None, body
        assert intent_answer["id"]
        assert intent_answer.get("status") in {"persisted", "succeeded"}

    run_async(scenario)


def test_finalization_writes_light_event(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        owner = await bootstrap(async_client, device_id="pytest-light-event-owner")
        draft = await chat_turn(
            async_client,
            conversation_id=owner["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        help_card_id = draft["help_cards"][0]["id"]

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

    run_async(scenario)
