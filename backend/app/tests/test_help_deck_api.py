from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import Conversation, HelpAnswer, HelpCard, Question, RewardEvent, Turn
from app.services.runtime import ensure_user, session_scope, utcnow


def _seed_help_card(
    *,
    owner_device: str,
    title: str,
    context_text: str,
    answer_count: int = 0,
    status: str = "published",
) -> str:
    with session_scope() as session:
        owner = ensure_user(session, device_uid=owner_device)
        conversation = Conversation(user_id=owner.id, status="active")
        session.add(conversation)
        session.flush()
        turn = Turn(
            conversation_id=conversation.id,
            user_id=owner.id,
            role="user",
            content=title,
            turn_index=1,
            status="recorded",
        )
        session.add(turn)
        session.flush()
        question = Question(
            conversation_id=conversation.id,
            turn_id=turn.id,
            user_id=owner.id,
            raw_text=title,
            normalized_text=title,
            status="waiting_for_human",
        )
        session.add(question)
        session.flush()
        help_card = HelpCard(
            question_id=question.id,
            conversation_id=conversation.id,
            owner_user_id=owner.id,
            title=title,
            prompt=title,
            context_text=context_text,
            status=status,
            answer_count=answer_count,
            min_answers_required=3,
            payload_json={
                "version": "onsite_food_beijing_v1",
                "location_state": "in_area",
                "context": {"scene": context_text},
                "wants": ["一句明确建议"],
                "avoids": ["绕远"],
                "constraints": [],
                "reward": {"label": "+10", "value": 10, "status": "pending"},
            },
            published_at=utcnow(),
        )
        session.add(help_card)
        session.flush()
        return str(help_card.id)


def _answer_card(*, help_card_id: str, answer_device: str, text: str = "我会选这个。") -> None:
    with session_scope() as session:
        answer_user = ensure_user(session, device_uid=answer_device)
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        assert help_card is not None
        answer = HelpAnswer(
            help_card_id=help_card.id,
            answer_user_id=answer_user.id,
            raw_text=text,
            normalized_text=text,
            status="submitted",
            reward_status="pending",
            evidence_json={"evidence_type": "human_one_liner"},
        )
        session.add(answer)
        help_card.answer_count += 1


def _reward_count_for_answer(answer_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(RewardEvent)
                .where(RewardEvent.help_answer_id == uuid.UUID(answer_id))
            )
            or 0
        )


async def _get_feed(client: AsyncClient, *, device_id: str, limit: int = 10) -> dict[str, Any]:
    response = await client.get("/v1/help-feed", params={"device_id": device_id, "limit": limit})
    assert response.status_code == 200, response.text
    return response.json()


def test_help_feed_filters_owner_and_answered_cards(run_async: Any, async_client: AsyncClient) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        owner_device = f"pytest-help-deck-owner-{suffix}"
        answer_device = f"pytest-help-deck-answer-{suffix}"
        stranger_device = f"pytest-help-deck-stranger-{suffix}"
        owner_card_id = _seed_help_card(
            owner_device=owner_device,
            title="韩国逛街不去明洞，求一句",
            context_text="想小众，别太游客。",
        )
        answered_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-other-owner-{suffix}",
            title="京都晚上吃什么",
            context_text="晚上想吃点轻松的。",
        )
        visible_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-visible-owner-{suffix}",
            title="大同晚上吃什么",
            context_text="晚上想吃本地味道。",
        )
        _answer_card(help_card_id=answered_card_id, answer_device=answer_device)

        owner_feed = await _get_feed(async_client, device_id=owner_device)
        assert owner_card_id not in {item["id"] for item in owner_feed["items"]}

        answerer_feed = await _get_feed(async_client, device_id=answer_device)
        assert answered_card_id not in {item["id"] for item in answerer_feed["items"]}

        stranger_feed = await _get_feed(async_client, device_id=stranger_device)
        visible = {item["id"]: item for item in stranger_feed["items"]}
        assert visible_card_id in visible
        assert visible[visible_card_id]["context_text"] == "晚上想吃本地味道。"
        assert visible[visible_card_id]["reward"]["label"] == "+10"
        assert isinstance(visible[visible_card_id]["answer_count"], int)

    run_async(scenario)


def test_one_liner_creates_answer_reward_event_and_advances(run_async: Any, async_client: AsyncClient) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-submit-{suffix}",
            title="五道口韩餐，求一句",
            context_text="想吃韩餐，不想排太久。",
        )
        response = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "device_id": f"pytest-help-deck-answer-submit-{suffix}",
                "text": "选五道口那家韩餐，翻台快一点。",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["accepted"] is True
        assert body["reward"] == {"label": "+10", "value": 10, "status": "pending"}
        assert body["should_advance"] is True
        assert body["help_card"]["answer_count"] == 1
        assert body["toast"] == "收到了，+10 等她采纳。"
        assert _reward_count_for_answer(body["answer_id"]) == 1

    run_async(scenario)


def test_one_liner_rejects_owner_duplicate_and_bad_text(run_async: Any, async_client: AsyncClient) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        owner_device = f"pytest-help-deck-owner-guard-{suffix}"
        answer_device = f"pytest-help-deck-answer-guard-{suffix}"
        help_card_id = _seed_help_card(
            owner_device=owner_device,
            title="朝阳区热干面，求一句",
            context_text="在朝阳区，想吃热干面。",
        )

        too_short = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"device_id": answer_device, "text": "好"},
        )
        assert too_short.status_code == 422

        owner_response = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"device_id": owner_device, "text": "我自己答一下"},
        )
        assert owner_response.status_code == 403

        first = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"device_id": answer_device, "text": "可以去附近那家，别绕路。"},
        )
        assert first.status_code == 200, first.text

        duplicate = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"device_id": answer_device, "text": "再答一次"},
        )
        assert duplicate.status_code == 409

    run_async(scenario)
