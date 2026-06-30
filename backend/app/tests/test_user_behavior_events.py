from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import AgentRun, RecommendationCard, UserBehaviorEvent
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


def test_chat_turn_and_card_feedback_preserve_experiment_assignment(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-experiment-event-{uuid.uuid4()}"
        boot = await bootstrap(async_client, device_id=device_id)
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        experiments = body["metadata"]["experiments"]
        assignments = experiments["assignments"]
        assert assignments
        assert experiments["variant_ids"]["pipi_card_copy_v1"] == assignments[0]["variant_id"]

        card_id = str(body["cards"][0]["id"])
        agent_run_id = str(body["metadata"]["agent_run_id"])
        with session_scope() as session:
            agent_run = session.get(AgentRun, uuid.UUID(agent_run_id))
            assert agent_run is not None
            assert agent_run.input_json["experiment_assignments"] == assignments
            assert agent_run.output_json["metadata"]["experiment_assignments"] == assignments

            card = session.get(RecommendationCard, uuid.UUID(card_id))
            assert card is not None
            assert card.payload_json["experiment_assignments"] == assignments

        accepted = await async_client.post(f"/v1/cards/{card_id}/accept", json={"device_id": device_id})
        require_ready_response(accepted)

        with session_scope() as session:
            event = session.scalar(
                select(UserBehaviorEvent)
                .where(
                    UserBehaviorEvent.recommendation_card_id == uuid.UUID(card_id),
                    UserBehaviorEvent.event_type == "recommendation_card_accepted",
                )
                .order_by(UserBehaviorEvent.created_at.desc())
            )
            assert event is not None
            assert event.payload_json["experiment_assignments"] == assignments
            assert event.payload_json["experiment_variant_ids"] == experiments["variant_ids"]

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


def test_generic_behavior_event_endpoint_records_drawer_core_event(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-behavior-drawer-{uuid.uuid4()}"
        boot = await bootstrap(async_client, device_id=device_id)
        response = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "conversation_id": boot["conversation_id"],
                "event_type": "drawer_history_pinned",
                "source": "ios",
                "metadata": {"surface": "drawer", "history_id": str(uuid.uuid4())},
            },
        )
        body = require_ready_response(response)
        assert body["accepted"] is True
        assert body["event"]["event_type"] == "drawer_history_pinned"
        assert body["event"]["metadata"]["known_core_event"] is True
        assert _event_count(
            event_type="drawer_history_pinned",
            conversation_id=uuid.UUID(boot["conversation_id"]),
        ) == 1

    run_async(scenario)


def test_my_favorites_reconstructs_saved_removed_and_restored_events(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-favorites-{uuid.uuid4()}"
        history_id = str(uuid.uuid4())
        saved = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "event_type": "favorite_choice_saved",
                "metadata": {
                    "history_id": history_id,
                    "query": "我想吃川菜",
                    "status": "saved",
                    "title": "三里屯川菜，就选这家",
                    "subtitle": "三里屯 · 川菜",
                    "reason": "你保存过这个选择。",
                    "surface": "favorites",
                },
            },
        )
        assert saved.status_code == 200, saved.text

        mine = await async_client.get("/v1/favorites/mine", params={"device_id": device_id})
        assert mine.status_code == 200, mine.text
        items = mine.json()["items"]
        assert [item["id"] for item in items] == [history_id]
        assert items[0]["query"] == "我想吃川菜"
        assert items[0]["top_pick"]["title"] == "三里屯川菜，就选这家"

        removed = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "event_type": "favorite_choice_removed",
                "metadata": {"history_id": history_id, "surface": "favorites"},
            },
        )
        assert removed.status_code == 200, removed.text
        mine_after_remove = await async_client.get("/v1/favorites/mine", params={"device_id": device_id})
        assert mine_after_remove.status_code == 200, mine_after_remove.text
        assert mine_after_remove.json()["items"] == []

        restored = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "event_type": "favorite_choice_restored",
                "metadata": {"history_id": history_id, "surface": "favorites"},
            },
        )
        assert restored.status_code == 200, restored.text
        mine_after_restore = await async_client.get("/v1/favorites/mine", params={"device_id": device_id})
        assert mine_after_restore.status_code == 200, mine_after_restore.text
        restored_items = mine_after_restore.json()["items"]
        assert [item["id"] for item in restored_items] == [history_id]
        assert restored_items[0]["top_pick"]["title"] == "三里屯川菜，就选这家"

    run_async(scenario)


def test_behavior_event_updates_user_preference_memory(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-preference-memory-{uuid.uuid4()}"
        await bootstrap(async_client, device_id=device_id)

        response = await async_client.post(
            "/v1/events",
            json={
                "device_id": device_id,
                "event_type": "ask_human_requested",
                "source": "ios",
                "metadata": {
                    "cuisine": "粤菜",
                    "taste_preference": ["清淡", "安静"],
                    "spice_preference": "not_spicy",
                    "budget_preference": "budget_low",
                    "companion": "parents",
                    "area": "望京",
                },
            },
        )
        require_ready_response(response)

        preferences = await async_client.get(
            "/v1/users/preferences",
            params={"device_uid": device_id},
        )
        body = require_ready_response(preferences)
        memory = body["preference_memory"]
        summary = memory["summary"]
        assert memory["explicit_signal_count"] == 1
        assert summary["top_cuisines"][0]["value"] == "粤菜"
        assert {item["value"] for item in summary["taste_preferences"]} >= {"清淡", "安静"}
        assert summary["spice_preferences"][0]["value"] == "not_spicy"
        assert summary["budget_preferences"][0]["value"] == "budget_low"
        assert summary["companions"][0]["value"] == "parents"
        assert summary["areas"][0]["value"] == "望京"

    run_async(scenario)


def test_card_reject_and_change_routes_write_feedback_events(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-card-feedback-{uuid.uuid4()}"
        boot = await bootstrap(async_client, device_id=device_id)
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        card_id = str(body["cards"][0]["id"])

        rejected = await async_client.post(
            f"/v1/cards/{card_id}/reject",
            json={
                "device_id": device_id,
                "reason": "不想吃面",
                "tags": ["不想吃面", "换口味"],
                "metadata": {"surface": "chat_card"},
            },
        )
        rejected_body = require_ready_response(rejected)
        assert rejected_body["accepted"] is False
        assert rejected_body["feedback"]["action"] == "reject"
        assert rejected_body["event"]["event_type"] == "recommendation_card_rejected"
        assert _event_count(
            event_type="recommendation_card_rejected",
            recommendation_card_id=uuid.UUID(card_id),
        ) == 1
        with session_scope() as session:
            card = session.get(RecommendationCard, uuid.UUID(card_id))
            assert card is not None
            assert card.status == "rejected"

        changed = await async_client.post(
            f"/v1/cards/{card_id}/change",
            json={
                "device_id": device_id,
                "reason": "想再来一个",
                "metadata": {"surface": "chat_card"},
            },
        )
        changed_body = require_ready_response(changed)
        assert changed_body["accepted"] is False
        assert changed_body["feedback"]["action"] == "change"
        assert changed_body["feedback"]["previous_status"] == "rejected"
        assert changed_body["event"]["event_type"] == "recommendation_card_changed"
        assert _event_count(
            event_type="recommendation_card_changed",
            recommendation_card_id=uuid.UUID(card_id),
        ) == 1
        with session_scope() as session:
            card = session.get(RecommendationCard, uuid.UUID(card_id))
            assert card is not None
            assert card.status == "changed"

    run_async(scenario)


def test_card_ask_human_route_writes_bound_feedback_event(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        device_id = f"pytest-card-ask-human-{uuid.uuid4()}"
        boot = await bootstrap(async_client, device_id=device_id)
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        card_id = str(body["cards"][0]["id"])

        asked = await async_client.post(
            f"/v1/cards/{card_id}/ask-human",
            json={
                "device_id": device_id,
                "reason": "想听真人意见",
                "metadata": {"surface": "chat_card"},
            },
        )

        asked_body = require_ready_response(asked)
        assert asked_body["accepted"] is False
        assert asked_body["feedback"]["action"] == "ask_human"
        assert asked_body["feedback"]["status"] == "asked_human"
        assert asked_body["event"]["event_type"] == "ask_human_requested"
        assert _event_count(
            event_type="ask_human_requested",
            recommendation_card_id=uuid.UUID(card_id),
        ) == 1
        with session_scope() as session:
            card = session.get(RecommendationCard, uuid.UUID(card_id))
            assert card is not None
            assert card.status == "asked_human"
            event = session.scalar(
                select(UserBehaviorEvent).where(
                    UserBehaviorEvent.recommendation_card_id == card.id,
                    UserBehaviorEvent.event_type == "ask_human_requested",
                )
            )
            assert event is not None
            assert event.payload_json["reason"] == "想听真人意见"
            assert event.payload_json["known_core_event"] is True

    run_async(scenario)
