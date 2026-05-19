from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import build_pipi_chat_graph
from app.agent.card_composer import compose_card_draft
from app.models import (
    AgentRun,
    HelpCard,
    ImageAsset,
    IntentAnswer,
    LightEvent,
    Question,
    RecommendationCard,
    RetrievalHit,
    RetrievalRun,
)
from app.services.runtime import (
    build_card_ui_event,
    build_help_ui_event,
    create_question_for_turn,
    create_tool_call,
    create_turn,
    ensure_datong_assets,
    ensure_seongsu_assets,
    ensure_seongsu_image,
    ensure_shopping_intent,
    ensure_user,
    finish_tool_call,
    get_or_create_conversation,
    latest_active_help_card,
    latest_question,
    serialize_card,
    serialize_help_card,
    serialize_light_event,
    serialize_retrieval,
    serialize_tool_call,
    session_scope,
    utcnow,
)


def bootstrap(payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        user = ensure_user(
            session,
            device_uid=payload.get("device_id") or payload.get("device_uid"),
            user_id=payload.get("user_id"),
            platform=payload.get("platform") or payload.get("metadata", {}).get("platform"),
            app_version=payload.get("app_version") or payload.get("metadata", {}).get("app_version"),
        )
        conversation = get_or_create_conversation(session, user=user, always_create=True)
        return {
            "conversation_id": str(conversation.id),
            "user_id": str(user.id),
            "help_feed": [],
            "light_events": [],
            "metadata": {"device_uid": user.device_uid},
        }


def run_chat_turn(payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        conversation, user = _resolve_conversation_and_user(session, payload)
        user_turn = create_turn(
            session,
            conversation=conversation,
            user=user,
            role="user",
            content=payload["message"],
            content_json={"client_turn_id": payload.get("client_turn_id"), "metadata": payload.get("metadata", {})},
        )
        question = _question_for_message(session, conversation=conversation, user=user, turn=user_turn, payload=payload)
        agent_run = AgentRun(
            conversation_id=conversation.id,
            turn_id=user_turn.id,
            run_type="pipi_chat",
            graph_name="PipiChatGraph",
            model_provider="deterministic",
            model_name="deterministic-v0",
            status="running",
            input_json={"message": payload["message"], "metadata": payload.get("metadata", {})},
        )
        session.add(agent_run)
        session.flush()

        active_help_card = _active_help_card(session, conversation.id, payload.get("metadata", {}))
        retriever = DbKnowledgeRetriever(session, agent_run=agent_run, turn=user_turn, question=question)
        executor = DbToolExecutor(
            session,
            agent_run=agent_run,
            turn=user_turn,
            user_id=user.id,
            question=question,
            active_help_card=active_help_card,
        )
        state = build_pipi_chat_graph().invoke(
            {
                "conversation_id": str(conversation.id),
                "user_turn_id": str(user_turn.id),
                "user_message": payload["message"],
                "agent_run_id": str(agent_run.id),
                "metadata": {
                    **(payload.get("metadata") or {}),
                    "knowledge_retriever": retriever,
                    "tool_executor": executor,
                    "active_help_card_id": str(active_help_card.id) if active_help_card else None,
                },
            }
        )

        assistant_message = state.get("assistant_message") or "皮皮已处理这一句。"
        assistant_turn = create_turn(
            session,
            conversation=conversation,
            user=None,
            role="assistant",
            content=assistant_message,
            content_json={"graph_state": _safe_state(state)},
        )
        agent_run.status = "succeeded"
        agent_run.output_json = _safe_state(state)
        agent_run.finished_at = utcnow()

        cards = executor.cards
        help_cards = executor.help_cards
        light_events = executor.light_events
        tool_calls = executor.tool_calls
        retrieval = retriever.retrieval_run
        metadata: dict[str, Any] = {"retrieval_run": serialize_retrieval(retrieval)}
        if executor.intent_answer is not None:
            metadata["intent_answer"] = {"id": str(executor.intent_answer.id), "status": "persisted"}
        if executor.ui_events:
            metadata["ui_events"] = executor.ui_events

        return {
            "conversation_id": str(conversation.id),
            "user_turn_id": str(user_turn.id),
            "assistant_turn_id": str(assistant_turn.id),
            "assistant_message": assistant_message,
            "cards": [serialize_card(card) for card in cards],
            "help_cards": [serialize_help_card(card) for card in help_cards],
            "light_events": [serialize_light_event(event) for event in light_events],
            "tool_calls": [serialize_tool_call(call) for call in tool_calls],
            "metadata": metadata,
        }


class DbKnowledgeRetriever:
    def __init__(
        self,
        session: Session,
        *,
        agent_run: AgentRun,
        turn: Any,
        question: Question | None,
    ) -> None:
        self.session = session
        self.agent_run = agent_run
        self.turn = turn
        self.question = question
        self.retrieval_run: RetrievalRun | None = None

    def retrieve(self, state: dict[str, Any]) -> dict[str, Any]:
        query = state["user_message"]
        normalized_query = query.lower()
        run = RetrievalRun(
            agent_run_id=self.agent_run.id,
            turn_id=self.turn.id,
            query=query,
            source="deterministic_db",
            status="succeeded",
            top_k=8,
            filters_json={
                "question_id": str(self.question.id) if self.question else None,
            },
        )
        self.session.add(run)
        self.session.flush()
        self.retrieval_run = run

        hits: list[dict[str, Any]] = []
        if "大同" in query or "喜晋道" in query:
            image, answer = ensure_datong_assets(self.session)
            hit = self._add_hit(
                run,
                source_type="intent_answer",
                source_id=str(answer.id),
                title="大同喜晋道到店不知道点什么",
                snippet=answer.answer_text,
                score=0.93,
                payload={
                    "has_verified_non_ai_image": True,
                    "image_asset_id": str(image.id),
                    "intent_answer_id": str(answer.id),
                    "title": "喜晋道 · 招牌刀削面",
                },
            )
            hits.append(hit)
        elif any(
            keyword in normalized_query
            for keyword in ("韩国", "明洞", "小众", "圣水", "korea", "myeongdong", "seongsu", "shopping")
        ):
            image, answer = ensure_seongsu_assets(self.session)
            hit = self._add_hit(
                run,
                source_type="intent_answer",
                source_id=str(answer.id),
                title="韩国逛街不去明洞想小众",
                snippet=answer.answer_text,
                score=0.88,
                payload={
                    "has_verified_non_ai_image": True,
                    "image_asset_id": str(image.id),
                    "intent_answer_id": str(answer.id),
                    "place_key": "korea-seongsu",
                    "title": "去圣水",
                    "subtitle": "别去明洞当背景板了，这次去圣水更适合你。",
                    "reason": "它比明洞更生活方式，也更适合买小众品牌、逛咖啡店和顺手买美妆。",
                    "bullets": ["小店密度高", "咖啡和生活方式品牌多", "比明洞更适合慢慢逛"],
                    "warning": "如果你只想买游客爆款和免税店，明洞会更直接。",
                },
            )
            hits.append(hit)

        return {
            "id": str(run.id),
            "query": query,
            "hits": hits,
            "metadata": {"status": "persisted"},
        }

    def _add_hit(
        self,
        run: RetrievalRun,
        *,
        source_type: str,
        source_id: str,
        title: str,
        snippet: str,
        score: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        hit = RetrievalHit(
            retrieval_run=run,
            rank=len(run.hits) + 1,
            score=score,
            source_type=source_type,
            source_id=source_id,
            title=title,
            snippet=snippet,
            payload_json=payload,
        )
        self.session.add(hit)
        self.session.flush()
        return {
            "source_id": str(hit.id),
            "title": title,
            "score": score,
            "payload": {**payload, "retrieval_hit_id": str(hit.id)},
        }


class DbToolExecutor:
    def __init__(
        self,
        session: Session,
        *,
        agent_run: AgentRun,
        turn: Any,
        user_id: uuid.UUID,
        question: Question | None,
        active_help_card: HelpCard | None,
    ) -> None:
        self.session = session
        self.agent_run = agent_run
        self.turn = turn
        self.user_id = user_id
        self.question = question
        self.active_help_card = active_help_card
        self.tool_calls: list[Any] = []
        self.cards: list[RecommendationCard] = []
        self.help_cards: list[HelpCard] = []
        self.light_events: list[LightEvent] = []
        self.ui_events: list[dict[str, Any]] = []
        self.intent_answer: Any | None = None

    def execute(self, tool_call: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        name = tool_call["name"]
        call = create_tool_call(
            self.session,
            agent_run=self.agent_run,
            turn=self.turn,
            name=name,
            arguments=tool_call.get("arguments", {}),
            sequence_index=len(self.tool_calls),
        )
        self.tool_calls.append(call)
        try:
            if name == "create_recommendation_card":
                result = self._create_recommendation(state, call)
            elif name == "create_help_card":
                result = self._create_help_card(state, call)
            elif name == "publish_help_card":
                result = self._publish_help_card(state, call)
            elif name == "finalize_recommendation":
                result = self._finalize_help_card(state, call)
            else:
                result = {"status": "ignored", "tool_name": name}
            finish_tool_call(call, status="succeeded", result=result)
            return {"status": "succeeded", "name": name, "result": result}
        except Exception as exc:
            finish_tool_call(call, status="failed", error=str(exc))
            raise

    def _create_recommendation(self, state: dict[str, Any], tool_call: Any) -> dict[str, Any]:
        if self.question is None:
            raise ValueError("question required")
        primary_hit = self._card_ready_hit(state)
        if primary_hit:
            image, answer = self._assets_from_payload(dict(primary_hit.get("payload") or {}))
            draft = compose_card_draft(
                user_message=state["user_message"],
                primary_hit=primary_hit,
                all_hits=state.get("retrieval_hits", []),
                intent_answer=answer,
                image_asset=image,
            )
        else:
            image, answer = ensure_datong_assets(self.session)
            primary_hit = self._fallback_hit(image=image, answer=answer)
            draft = compose_card_draft(
                user_message=state["user_message"],
                primary_hit=primary_hit,
                all_hits=[primary_hit],
                intent_answer=answer,
                image_asset=image,
            )

        self._assert_card_image(image)
        card = RecommendationCard(
            question_id=self.question.id,
            conversation_id=self.question.conversation_id,
            user_id=self.user_id,
            agent_run_id=self.agent_run.id,
            tool_call_id=tool_call.id,
            image_asset_id=image.id,
            source="pipi_chat_graph",
            title=draft.title,
            subtitle=draft.subtitle,
            reason=draft.reason,
            bullets_json=draft.bullets,
            warning=draft.warning,
            confidence=draft.confidence,
            status="active",
            payload_json={
                "intent_answer_id": str(answer.id) if answer else None,
                "evidence_ids": [hit.get("source_id") for hit in state.get("retrieval_hits", [])],
                "followups": draft.followups,
                "composer": {
                    "provider": draft.model_provider,
                    "model": draft.model_name,
                    "used_web_search": draft.used_web_search,
                    **draft.metadata,
                },
            },
        )
        self.session.add(card)
        self.session.flush()
        self.question.current_recommendation_card_id = card.id
        self.question.status = "top1_ready"
        self.cards.append(card)
        self.intent_answer = answer
        self.ui_events.append(build_card_ui_event(card))
        return {"card_id": str(card.id), "ui_event": "show_recommendation_card"}

    def _card_ready_hit(self, state: dict[str, Any]) -> dict[str, Any] | None:
        for hit in state.get("retrieval_hits", []):
            payload = dict(hit.get("payload") or {})
            if not payload.get("has_verified_non_ai_image") or not payload.get("image_asset_id"):
                continue
            return hit
        return None

    def _assets_from_payload(self, payload: dict[str, Any]) -> tuple[ImageAsset, IntentAnswer | None]:
        image = self.session.get(ImageAsset, uuid.UUID(str(payload["image_asset_id"])))
        if image is None:
            raise ValueError("recommendation image asset missing")

        answer: IntentAnswer | None = None
        if payload.get("intent_answer_id"):
            answer = self.session.get(IntentAnswer, uuid.UUID(str(payload["intent_answer_id"])))
        return image, answer

    def _assert_card_image(self, image: ImageAsset) -> None:
        if not image.verified or image.verification_status != "verified" or image.is_ai_generated:
            raise ValueError("recommendation cards require verified non-AI image assets")

    def _fallback_hit(self, image: ImageAsset, answer: IntentAnswer) -> dict[str, Any]:
        return {
            "source_id": str(answer.id),
            "title": "大同喜晋道到店不知道点什么",
            "score": 0.92,
            "payload": {
                "has_verified_non_ai_image": True,
                "image_asset_id": str(image.id),
                "intent_answer_id": str(answer.id),
            },
        }

    def _create_help_card(self, state: dict[str, Any], tool_call: Any) -> dict[str, Any]:
        if self.question is None:
            raise ValueError("question required")
        message = state["user_message"]
        title = "在韩国逛街，不想去明洞" if any(k in message for k in ("韩国", "明洞")) else message[:60]
        help_card = HelpCard(
            question_id=self.question.id,
            conversation_id=self.question.conversation_id,
            owner_user_id=self.user_id,
            title=title,
            prompt=title,
            context_text=f"用户说：{message}。先收集懂的人一句建议。",
            status="draft",
            min_answers_required=3,
            answer_count=0,
            payload_json={"missing_info": ["预算", "风格偏好", "同行人"]},
        )
        self.session.add(help_card)
        self.session.flush()
        self.question.current_help_card_id = help_card.id
        self.question.status = "ask_draft_ready"
        self.help_cards.append(help_card)
        self.active_help_card = help_card
        self.ui_events.append(build_help_ui_event(help_card))
        return {"help_card_id": str(help_card.id), "ui_event": "show_help_card_draft"}

    def _publish_help_card(self, state: dict[str, Any], tool_call: Any) -> dict[str, Any]:
        help_card = self._selected_help_card(state)
        if help_card.owner_user_id != self.user_id:
            raise PermissionError("only owner can publish help card")
        if help_card.status == "draft":
            help_card.status = "published"
            help_card.published_at = utcnow()
            help_card.question.status = "help_published"
        self.help_cards.append(help_card)
        self.ui_events.append(build_help_ui_event(help_card, "help_card_published"))
        return {"help_card_id": str(help_card.id), "ui_event": "help_card_published"}

    def _finalize_help_card(self, state: dict[str, Any], tool_call: Any) -> dict[str, Any]:
        help_card = self._selected_help_card(state)
        card = finalize_help_card_now(self.session, help_card=help_card, agent_run=self.agent_run, tool_call=tool_call)
        self.cards.append(card)
        if help_card.final_recommendation_card is not None:
            self.help_cards.append(help_card)
        events = list(
            self.session.scalars(
                select(LightEvent)
                .where(LightEvent.help_card_id == help_card.id)
                .order_by(LightEvent.created_at.desc())
                .limit(1)
            )
        )
        self.light_events.extend(events)
        self.ui_events.append(build_card_ui_event(card))
        return {"card_id": str(card.id), "ui_event": "show_recommendation_card"}

    def _selected_help_card(self, state: dict[str, Any]) -> HelpCard:
        metadata = state.get("metadata", {})
        help_card_id = metadata.get("help_card_id") or metadata.get("active_help_card_id")
        help_card = self.active_help_card
        if help_card_id:
            help_card = self.session.get(HelpCard, uuid.UUID(str(help_card_id)))
        if help_card is None:
            raise ValueError("active help card required")
        return help_card


def finalize_help_card_now(
    session: Session,
    *,
    help_card: HelpCard,
    agent_run: AgentRun | None = None,
    tool_call: Any | None = None,
) -> RecommendationCard:
    if help_card.final_recommendation_card is not None:
        return help_card.final_recommendation_card
    if help_card.answer_count < help_card.min_answers_required:
        raise ValueError("not enough answers to finalize")

    image = ensure_seongsu_image(session)
    intent = ensure_shopping_intent(session)
    card = RecommendationCard(
        question_id=help_card.question_id,
        conversation_id=help_card.conversation_id,
        user_id=help_card.owner_user_id,
        agent_run_id=agent_run.id if agent_run else None,
        tool_call_id=tool_call.id if tool_call else None,
        image_asset_id=image.id,
        source="pipi_finalized_from_help",
        title="去圣水",
        subtitle="别去明洞当背景板了，这次去圣水更适合你。",
        reason="它比明洞更生活方式，也更适合买小众品牌、逛咖啡店和顺手买美妆。",
        bullets_json=["小店密度高", "咖啡和生活方式品牌多", "比明洞更适合慢慢逛"],
        warning="如果你只想买游客爆款和免税店，明洞会更直接。",
        confidence=0.86,
        status="active",
        payload_json={"source_help_card_id": str(help_card.id)},
    )
    session.add(card)
    session.flush()

    intent_answer = IntentAnswer(
        intent_id=intent.id,
        image_asset_id=image.id,
        answer_text=card.reason,
        locale="zh-CN",
        tags_json=["help_final", "korea", "seongsu"],
        evidence_json={"source_type": "help_final", "help_card_id": str(help_card.id)},
        priority=30,
        is_active=True,
    )
    session.add(intent_answer)

    help_card.final_recommendation_card_id = card.id
    help_card.status = "final_ready"
    help_card.final_ready_at = utcnow()
    help_card.question.current_recommendation_card_id = card.id
    help_card.question.status = "final_ready"
    for answer in help_card.answers:
        answer.status = "used"
        answer.reward_status = "granted"

    light = LightEvent(
        user_id=help_card.owner_user_id,
        conversation_id=help_card.conversation_id,
        question_id=help_card.question_id,
        help_card_id=help_card.id,
        recommendation_card_id=card.id,
        type="final_ready",
        title="有人帮你选好了",
        body=f"{help_card.title} 有结果了。",
        payload_json={"card_id": str(card.id)},
    )
    session.add(light)
    session.flush()
    return card


def _resolve_conversation_and_user(session: Session, payload: dict[str, Any]) -> tuple[Any, Any]:
    conversation_id = payload.get("conversation_id")
    if conversation_id:
        from app.models import Conversation

        conversation = session.get(Conversation, uuid.UUID(conversation_id))
        if conversation is None:
            raise ValueError("conversation not found")
        return conversation, conversation.user

    user = ensure_user(
        session,
        device_uid=payload.get("device_id") or payload.get("device_uid") or payload.get("user_id"),
        user_id=payload.get("user_id"),
    )
    conversation = get_or_create_conversation(session, user=user, always_create=True)
    return conversation, user


def _question_for_message(
    session: Session,
    *,
    conversation: Any,
    user: Any,
    turn: Any,
    payload: dict[str, Any],
) -> Question | None:
    message = payload["message"]
    if any(keyword in message for keyword in ("发出去", "发个求助", "发布", "最终", "final")):
        return latest_question(session, conversation_id=conversation.id)
    return create_question_for_turn(session, conversation=conversation, user=user, turn=turn)


def _active_help_card(session: Session, conversation_id: uuid.UUID, metadata: dict[str, Any]) -> HelpCard | None:
    help_card_id = metadata.get("help_card_id")
    if help_card_id:
        return session.get(HelpCard, uuid.UUID(str(help_card_id)))
    return latest_active_help_card(session, conversation_id=conversation_id)


def _safe_state(state: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in state.items():
        if key == "metadata":
            safe[key] = {
                item_key: item_value
                for item_key, item_value in value.items()
                if isinstance(item_value, (str, int, float, bool, type(None), list, dict))
            }
        elif isinstance(value, (str, int, float, bool, type(None), list, dict)):
            safe[key] = value
    return safe
