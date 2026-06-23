from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.jobs.finalizer_job import run_finalize_graph_for_help_card
from app.models import ContentReviewTask, Conversation, HelpAnswer, HelpCard, Question, RewardEvent, Turn, UserBehaviorEvent
from app.services.runtime import ensure_user, session_scope, utcnow


def _seed_help_card(
    *,
    owner_device: str,
    title: str,
    context_text: str,
    answer_count: int = 0,
    status: str = "published",
    reward_value: int = 10,
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
                "reward": {"label": f"+{reward_value}", "value": reward_value, "status": "pending"},
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


def _reward_statuses_for_answer(answer_id: str) -> list[str]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(RewardEvent.status)
                .where(RewardEvent.help_answer_id == uuid.UUID(answer_id))
                .order_by(RewardEvent.created_at.asc())
            )
        )


def _help_answer_count(help_card_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(HelpAnswer)
                .where(HelpAnswer.help_card_id == uuid.UUID(help_card_id))
            )
            or 0
        )


def _reward_event_count_for_help_card(help_card_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(RewardEvent)
                .where(RewardEvent.help_card_id == uuid.UUID(help_card_id))
            )
            or 0
        )


def _content_review_tasks_for_help_card(
    help_card_id: str,
    *,
    task_type: str = "one_liner_rejected",
) -> list[ContentReviewTask]:
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(ContentReviewTask)
                .where(
                    ContentReviewTask.target_table == "help_cards",
                    ContentReviewTask.target_record_id == help_card_id,
                    ContentReviewTask.task_type == task_type,
                )
                .order_by(ContentReviewTask.created_at.asc())
            )
        )
        for row in rows:
            session.expunge(row)
        return rows


def _behavior_event_count_for_answer(*, answer_id: str, event_type: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(UserBehaviorEvent)
                .where(
                    UserBehaviorEvent.help_answer_id == uuid.UUID(answer_id),
                    UserBehaviorEvent.event_type == event_type,
                )
            )
            or 0
        )


def _seed_answers_with_rewards(
    *,
    help_card_id: str,
    answer_specs: list[tuple[str, str]],
) -> dict[str, str]:
    answer_ids: dict[str, str] = {}
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        assert help_card is not None
        for device, text in answer_specs:
            answer_user = ensure_user(session, device_uid=device)
            answer = HelpAnswer(
                help_card_id=help_card.id,
                answer_user_id=answer_user.id,
                raw_text=text,
                normalized_text=text,
                status="submitted",
                reward_status="pending",
                evidence_json={
                    "evidence_type": "human_one_liner",
                    "reward": {"label": "+10", "value": 10, "status": "pending"},
                },
            )
            session.add(answer)
            session.flush()
            session.add(
                RewardEvent(
                    user_id=answer_user.id,
                    help_card_id=help_card.id,
                    help_answer_id=answer.id,
                    event_type="one_liner_submitted",
                    label="+10",
                    value=10,
                    status="pending",
                    payload_json={"help_card_title": help_card.title},
                )
            )
            help_card.answer_count += 1
            answer_ids[device] = str(answer.id)
    return answer_ids


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


def test_help_card_unsafe_publish_is_blocked_and_hidden_from_feed(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        owner_device = f"pytest-help-deck-owner-unsafe-card-{suffix}"
        help_card_id = _seed_help_card(
            owner_device=owner_device,
            title="朝阳区热干面求一个，加我微信 vx123456",
            context_text="联系方式放这里。",
            status="draft",
        )

        blocked = await async_client.post(
            f"/v1/help-cards/{help_card_id}/publish",
            json={"device_id": owner_device, "metadata": {"source": "pytest"}},
        )

        assert blocked.status_code == 422, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "help_card_unsafe"
        assert "contact_spam" in detail["issues"]

        tasks = _content_review_tasks_for_help_card(help_card_id, task_type="help_card_rejected")
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "open"
        assert task.reason == "contact_spam"
        assert task.priority <= 20
        assert task.payload_json["source"] == "help_card_publish"
        assert task.payload_json["abuse"]["unsafe"] is True

        feed = await _get_feed(async_client, device_id=f"pytest-help-deck-reader-unsafe-card-{suffix}", limit=100)
        assert help_card_id not in {str(item["id"]) for item in feed["items"]}

    run_async(scenario)


def test_help_feed_filters_legacy_unsafe_published_cards(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-legacy-unsafe-{suffix}",
            title="国贸午饭求一个，加我微信 vx123456",
            context_text="明显联系方式。",
            status="published",
        )
        safe_help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-legacy-safe-{suffix}",
            title="国贸午饭求一个",
            context_text="想找现在能直接去的一家。",
            status="published",
        )

        feed = await _get_feed(async_client, device_id=f"pytest-help-deck-reader-legacy-unsafe-{suffix}", limit=100)
        ids = {str(item["id"]) for item in feed["items"]}
        assert help_card_id not in ids
        assert safe_help_card_id in ids

    run_async(scenario)


def test_help_feed_ranks_reward_scarcity_and_answer_count(run_async: Any, async_client: AsyncClient) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        high_reward_id = _seed_help_card(
            owner_device=f"pytest-help-deck-rank-high-owner-{suffix}",
            title="高奖励求一句",
            context_text="更值得答主先看。",
            answer_count=2,
            reward_value=30,
        )
        low_answer_id = _seed_help_card(
            owner_device=f"pytest-help-deck-rank-low-owner-{suffix}",
            title="低答案求一句",
            context_text="还缺很多答案。",
            answer_count=0,
            reward_value=10,
        )
        filled_id = _seed_help_card(
            owner_device=f"pytest-help-deck-rank-filled-owner-{suffix}",
            title="已快完成求一句",
            context_text="答案已经比较多。",
            answer_count=3,
            reward_value=10,
        )

        feed = await _get_feed(async_client, device_id=f"pytest-help-deck-rank-reader-{suffix}", limit=100)
        expected = {high_reward_id, low_answer_id, filled_id}
        relevant_items = [item for item in feed["items"] if item["id"] in expected]
        ids = [item["id"] for item in relevant_items]

        assert ids == [high_reward_id, low_answer_id, filled_id]
        assert relevant_items[0]["metadata"]["feed_ranking"]["reward_value"] == 30
        assert relevant_items[1]["metadata"]["feed_ranking"]["remaining_answers"] == 3

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


def test_one_liner_reward_becomes_granted_after_finalization(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-grant-{suffix}",
            title="韩国逛街不去明洞，求一句",
            context_text="想小众，别太游客。",
        )
        answer_devices = [f"pytest-help-deck-grant-answer-{index}-{suffix}" for index in range(3)]
        last_body: dict[str, Any] = {}
        for index, device_id in enumerate(answer_devices, start=1):
            text = [
                "去圣水更稳，小店密度高。",
                "圣水比明洞更小众，也适合买美妆。",
                "预算不高也能逛圣水，路线轻松。",
            ][index - 1]
            response = await async_client.post(
                f"/v1/help-cards/{help_card_id}/one-liner",
                json={"device_id": device_id, "text": text},
            )
            assert response.status_code == 200, response.text
            last_body = response.json()

        assert last_body["metadata"]["finalization_ready"] is True
        rewards = await async_client.get("/v1/rewards/me", params={"device_id": answer_devices[0]})
        assert rewards.status_code == 200, rewards.text
        body = rewards.json()
        assert body["pending_value"] == 0
        assert body["granted_value"] == 10
        assert body["rejected_value"] == 0
        assert body["items"][0]["status"] == "granted"

    run_async(scenario)


def test_finalizer_rejects_pending_rewards_not_selected_as_evidence(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        rejected_device = f"pytest-help-deck-reject-answer-bad-{suffix}"
        help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-reject-{suffix}",
            title="韩国逛街不去明洞，求一句",
            context_text="想小众，别太游客。",
        )
        answer_ids = _seed_answers_with_rewards(
            help_card_id=help_card_id,
            answer_specs=[
                (f"pytest-help-deck-reject-answer-1-{suffix}", "去圣水，小店多，也适合买美妆。"),
                (f"pytest-help-deck-reject-answer-2-{suffix}", "圣水比明洞更小众，咖啡店也密集。"),
                (f"pytest-help-deck-reject-answer-3-{suffix}", "预算不高也能逛圣水，路线轻松。"),
                (rejected_device, "随便"),
            ],
        )

        with session_scope() as session:
            run_finalize_graph_for_help_card(session, uuid.UUID(help_card_id))

        assert _reward_statuses_for_answer(answer_ids[rejected_device]) == ["rejected"]
        assert _behavior_event_count_for_answer(
            answer_id=answer_ids[rejected_device],
            event_type="one_liner_reward_rejected",
        ) == 1
        rewards = await async_client.get("/v1/rewards/me", params={"device_id": rejected_device})
        assert rewards.status_code == 200, rewards.text
        body = rewards.json()
        assert body["pending_value"] == 0
        assert body["granted_value"] == 0
        assert body["rejected_value"] == 10
        assert body["items"][0]["status"] == "rejected"

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


def test_one_liner_rejects_low_quality_and_cross_user_duplicate(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-quality-{suffix}",
            title="圣水逛街，求一句",
            context_text="想小众一点，避开游客区。",
        )

        low_quality = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={"device_id": f"pytest-help-deck-low-quality-{suffix}", "text": "随便"},
        )
        assert low_quality.status_code == 422
        assert low_quality.json()["detail"]["code"] == "one_liner_low_quality"
        assert _help_answer_count(help_card_id) == 0

        first = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "device_id": f"pytest-help-deck-dup-1-{suffix}",
                "text": "去圣水更稳，小店密度高。",
            },
        )
        assert first.status_code == 200, first.text
        answer_id = first.json()["answer_id"]
        assert _reward_count_for_answer(answer_id) == 1

        duplicate = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "device_id": f"pytest-help-deck-dup-2-{suffix}",
                "text": "去圣水更稳 小店密度高",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "duplicate_answer"
        assert _help_answer_count(help_card_id) == 1

    run_async(scenario)


def test_rejected_one_liner_creates_content_review_task(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        suffix = uuid.uuid4()
        help_card_id = _seed_help_card(
            owner_device=f"pytest-help-deck-owner-abuse-{suffix}",
            title="朝阳区热干面，求一句",
            context_text="在朝阳区，想吃热干面。",
        )

        unsafe = await async_client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "device_id": f"pytest-help-deck-abuse-answer-{suffix}",
                "text": "加我微信 vx123456，我详细告诉你",
                "metadata": {"source": "pytest"},
            },
        )

        assert unsafe.status_code == 422, unsafe.text
        detail = unsafe.json()["detail"]
        assert detail["code"] == "one_liner_unsafe"
        assert "contact_spam" in detail["issues"]
        assert _help_answer_count(help_card_id) == 0
        assert _reward_event_count_for_help_card(help_card_id) == 0

        tasks = _content_review_tasks_for_help_card(help_card_id)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "open"
        assert task.priority <= 20
        assert task.reason == "contact_spam"
        assert task.payload_json["source"] == "one_liner"
        assert task.payload_json["raw_text"] == "加我微信 vx123456，我详细告诉你"
        assert task.payload_json["abuse"]["unsafe"] is True
        assert "contact_spam" in task.payload_json["issues"]

    run_async(scenario)
