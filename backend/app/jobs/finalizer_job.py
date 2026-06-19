"""Deterministic finalizer job V0.

This module coordinates ready help cards with PipiFinalizeGraph. Tests and
future schedulers can still plug in queue/repository/tool interfaces; the
default V0 path uses the SQLAlchemy runtime tables directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol, TypedDict, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.pipi_finalize_graph import (
    FinalizeRepository,
    KnowledgeRetriever,
    PipiFinalizeGraph,
    PipiFinalizeGraphState,
    ToolInvoker,
)
from app.models import (
    AgentRun,
    HelpAnswer,
    HelpCard,
    ImageAsset,
    IntentAnswer,
    LightEvent,
    RecommendationCard,
    RetrievalHit,
    RetrievalRun,
)
from app.services.help_service import help_answer_text, human_one_liner_evidence
from app.services.intent_answer_service import (
    HELP_FINAL_SOURCE_TYPE,
    build_help_final_metadata,
    confidence_value,
)
from app.services.runtime import (
    create_tool_call,
    ensure_seongsu_assets,
    ensure_shopping_intent,
    finish_tool_call,
    session_scope,
    utcnow,
)


class FinalizerJobResult(TypedDict):
    """Summary returned by one finalizer job pass."""

    scanned: int
    finalized: int
    needs_more_answers: int
    failed: int
    states: list[PipiFinalizeGraphState]


@runtime_checkable
class FinalizerQueue(Protocol):
    """Future queue/persistence boundary for ready help cards."""

    def list_ready_help_cards(self, *, limit: int = 10) -> Sequence[Mapping[str, Any]]:
        """Return help cards ready to finalize."""


class PipiFinalizerJob:
    """Run PipiFinalizeGraph over ready help cards."""

    def __init__(
        self,
        *,
        queue: FinalizerQueue | None = None,
        repository: FinalizeRepository | None = None,
        retriever: KnowledgeRetriever | None = None,
        tools: ToolInvoker | Mapping[str, Any] | None = None,
        graph: PipiFinalizeGraph | None = None,
        limit: int = 10,
    ) -> None:
        self.queue = queue
        self.limit = limit
        self._use_default_db = (
            queue is None
            and repository is None
            and retriever is None
            and tools is None
            and graph is None
        )
        self.graph = graph or PipiFinalizeGraph(
            repository=repository,
            retriever=retriever,
            tools=tools,
        )

    def run_once(
        self,
        ready_help_cards: Iterable[Mapping[str, Any]] | None = None,
    ) -> FinalizerJobResult:
        """Finalize at most one batch of ready help cards."""

        if ready_help_cards is None and self._use_default_db:
            return self._run_default_db_once()

        cards = list(ready_help_cards) if ready_help_cards is not None else self._load_ready_help_cards()
        states: list[PipiFinalizeGraphState] = []
        finalized = 0
        needs_more_answers = 0
        failed = 0

        for card in cards[: self.limit]:
            try:
                state = self.graph.invoke(_state_from_help_card(card))
                states.append(state)
                if state.get("status") == "final_ready":
                    finalized += 1
                elif state.get("status") == "needs_more_answers":
                    needs_more_answers += 1
            except Exception as exc:  # pragma: no cover - defensive job boundary.
                failed += 1
                states.append(
                    {
                        "help_card_id": str(card.get("id") or card.get("help_card_id") or ""),
                        "status": "failed",
                        "warnings": [str(exc)],
                    }
                )

        return {
            "scanned": len(cards[: self.limit]),
            "finalized": finalized,
            "needs_more_answers": needs_more_answers,
            "failed": failed,
            "states": states,
        }

    def _load_ready_help_cards(self) -> list[Mapping[str, Any]]:
        if self.queue is None:
            return []
        return list(self.queue.list_ready_help_cards(limit=self.limit))

    def _run_default_db_once(self) -> FinalizerJobResult:
        with session_scope() as session:
            cards = list(DbFinalizerQueue(session).list_ready_help_cards(limit=self.limit))

        states: list[PipiFinalizeGraphState] = []
        finalized = 0
        needs_more_answers = 0
        failed = 0

        for card in cards:
            try:
                state = _run_db_finalization_for_card(card)
                states.append(state)
                if state.get("status") == "final_ready":
                    finalized += 1
                elif state.get("status") == "needs_more_answers":
                    needs_more_answers += 1
            except Exception as exc:  # pragma: no cover - defensive job boundary.
                failed += 1
                states.append(
                    {
                        "help_card_id": str(card.get("id") or card.get("help_card_id") or ""),
                        "status": "failed",
                        "warnings": [str(exc)],
                    }
                )

        return {
            "scanned": len(cards),
            "finalized": finalized,
            "needs_more_answers": needs_more_answers,
            "failed": failed,
            "states": states,
        }


class DbFinalizerQueue:
    """Database-backed queue for help cards ready to finalize."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_ready_help_cards(self, *, limit: int = 10) -> Sequence[Mapping[str, Any]]:
        query = (
            select(HelpCard)
            .where(
                HelpCard.status.in_(["published", "collecting"]),
                HelpCard.final_recommendation_card_id.is_(None),
                HelpCard.answer_count >= HelpCard.min_answers_required,
            )
            .order_by(HelpCard.updated_at.asc(), HelpCard.created_at.asc())
            .limit(limit)
        )
        return [_help_card_mapping(card) for card in self.session.scalars(query)]


class DbFinalizeRepository:
    """Load help-card snapshots and human answers for PipiFinalizeGraph."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def load_help_card(self, help_card_id: str) -> Mapping[str, Any] | None:
        help_card = self.session.get(HelpCard, uuid.UUID(help_card_id))
        if help_card is None:
            return None
        return _help_card_mapping(help_card)

    def load_help_answers(self, help_card_id: str) -> Sequence[Mapping[str, Any]]:
        query = (
            select(HelpAnswer)
            .where(HelpAnswer.help_card_id == uuid.UUID(help_card_id))
            .order_by(HelpAnswer.created_at.asc())
        )
        return [
            {
                "id": str(answer.id),
                "help_card_id": str(answer.help_card_id),
                "user_id": str(answer.answer_user_id) if answer.answer_user_id else "",
                "text": help_answer_text(answer),
                "status": answer.status,
                "metadata": human_one_liner_evidence(answer.evidence_json or {}),
            }
            for answer in self.session.scalars(query)
        ]


class DbFinalizeKnowledgeRetriever:
    """Persist deterministic retrieval runs/hits for finalization."""

    def __init__(self, session: Session, *, agent_run: AgentRun, help_card_id: uuid.UUID) -> None:
        self.session = session
        self.agent_run = agent_run
        self.help_card_id = help_card_id

    def retrieve(self, query: str, *, limit: int = 5) -> Mapping[str, Any]:
        run = RetrievalRun(
            agent_run_id=self.agent_run.id,
            turn_id=None,
            query=query or f"help_card:{self.help_card_id}",
            source="deterministic_finalize_graph",
            status="succeeded",
            top_k=limit,
            filters_json={"help_card_id": str(self.help_card_id)},
            metadata_json={"provider": "deterministic_v0", "stage": "finalize"},
            finished_at=utcnow(),
        )
        self.session.add(run)
        self.session.flush()

        hits: list[dict[str, Any]] = []
        rank = 1
        image, intent_answer = ensure_seongsu_assets(self.session)
        hits.append(
            self._add_hit(
                run,
                rank=rank,
                source_type="intent_answer",
                source_id=str(intent_answer.id),
                title="圣水适合替代明洞的小众逛街路线",
                snippet=intent_answer.answer_text,
                score=0.91,
                payload={
                    "intent_answer_id": str(intent_answer.id),
                    "image_asset_id": str(image.id),
                    "place_key": "korea-seongsu",
                    "item_key": "shopping-street",
                    "decision_factor": "比明洞更生活方式，也更适合买小众品牌和美妆。",
                },
            )
        )
        rank += 1

        answers = list(
            self.session.scalars(
                select(HelpAnswer)
                .where(HelpAnswer.help_card_id == self.help_card_id)
                .order_by(HelpAnswer.created_at.asc())
                .limit(max(limit - 1, 0))
            )
        )
        for answer in answers:
            text = help_answer_text(answer)
            hits.append(
                self._add_hit(
                    run,
                    rank=rank,
                    source_type="help_answer",
                    source_id=str(answer.id),
                    title="来一句",
                    snippet=text,
                    score=0.84,
                    payload={
                        "help_answer_id": str(answer.id),
                        "help_card_id": str(self.help_card_id),
                        **human_one_liner_evidence(answer.evidence_json or {}),
                    },
                )
            )
            rank += 1

        return {
            "id": str(run.id),
            "query": run.query,
            "hits": hits,
            "metadata": {"status": "persisted", "source": run.source},
        }

    def _add_hit(
        self,
        run: RetrievalRun,
        *,
        rank: int,
        source_type: str,
        source_id: str,
        title: str,
        snippet: str,
        score: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        hit = RetrievalHit(
            retrieval_run_id=run.id,
            rank=rank,
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


class DbFinalizeToolInvoker:
    """Persist finalizer tool calls and their side effects."""

    def __init__(self, session: Session, *, agent_run: AgentRun) -> None:
        self.session = session
        self.agent_run = agent_run
        self.sequence_index = 0

    def invoke_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
    ) -> Mapping[str, Any]:
        name = _standard_finalize_tool_name(name)
        tool_call = create_tool_call(
            self.session,
            agent_run=self.agent_run,
            turn=None,
            name=name,
            arguments=dict(arguments),
            sequence_index=self.sequence_index,
        )
        self.sequence_index += 1
        try:
            if name == "finalize_help_card":
                result = self._finalize_help_card(arguments, state)
            elif name == "create_recommendation_card":
                result = self._create_final_recommendation_card(arguments, state, tool_call)
            elif name == "save_intent_answer":
                result = self._save_intent_answer(arguments, state)
            elif name == "light_user":
                result = self._light_user(arguments)
            else:
                result = {"status": "ignored", "tool_name": name}
            finish_tool_call(tool_call, status="succeeded", result=dict(result))
            return result
        except Exception as exc:
            finish_tool_call(tool_call, status="failed", error=str(exc))
            raise

    def _finalize_help_card(
        self,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
    ) -> Mapping[str, Any]:
        del state
        help_card = _get_help_card(self.session, arguments["help_card_id"])
        if help_card.answer_count < help_card.min_answers_required:
            raise ValueError("not enough answers to finalize")
        return {
            "status": "ready",
            "help_card_id": str(help_card.id),
            "answer_count": help_card.answer_count,
            "min_answers_required": help_card.min_answers_required,
        }

    def _create_final_recommendation_card(
        self,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
        tool_call: Any,
    ) -> Mapping[str, Any]:
        help_card = _get_help_card(self.session, arguments["help_card_id"])
        if help_card.answer_count < help_card.min_answers_required:
            raise ValueError("not enough answers to finalize")
        if help_card.final_recommendation_card is not None:
            return _card_result(help_card.final_recommendation_card, status="already_final_ready")

        image, _ = ensure_seongsu_assets(self.session)
        _assert_card_image(image)
        evidence_answer_ids = list(arguments.get("evidence_answer_ids") or [])
        retrieval_hit_ids = list((arguments.get("metadata") or {}).get("retrieval_hit_ids") or [])
        decision_factor = str(arguments.get("decision_factor") or arguments.get("reason") or "")
        card = RecommendationCard(
            question_id=help_card.question_id,
            conversation_id=help_card.conversation_id,
            user_id=help_card.owner_user_id,
            agent_run_id=self.agent_run.id,
            tool_call_id=tool_call.id,
            image_asset_id=image.id,
            image_required=True,
            image_status="attached",
            source=str(arguments.get("source") or "pipi_finalized_from_help"),
            title=str(arguments.get("title") or "去圣水"),
            subtitle=None,
            reason=decision_factor,
            bullets_json=[],
            warning=None,
            confidence=float(arguments.get("confidence") or 0.86),
            status="active",
            payload_json={
                "source_help_card_id": str(help_card.id),
                "evidence_answer_ids": evidence_answer_ids,
                "retrieval_hit_ids": retrieval_hit_ids,
                "item": {"title": str(arguments.get("title") or "去圣水")},
                "decision_factor": {"text": decision_factor},
                "followups": [],
                "composer": {
                    "provider": "deterministic",
                    "model": "deterministic-v0",
                    "composition": "help_answers_finalized",
                },
            },
        )
        self.session.add(card)
        self.session.flush()

        help_card.final_recommendation_card_id = card.id
        help_card.status = "final_ready"
        help_card.final_ready_at = utcnow()
        help_card.question.current_recommendation_card_id = card.id
        help_card.question.status = "final_ready"
        for answer in help_card.answers:
            answer.status = "used"
            answer.reward_status = "granted"
        self.session.flush()
        return _card_result(card, status="persisted")

    def _save_intent_answer(
        self,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
    ) -> Mapping[str, Any]:
        del state
        help_card = _get_help_card(self.session, arguments["help_card_id"])
        image, _ = ensure_seongsu_assets(self.session)
        intent = ensure_shopping_intent(self.session)
        answer_text = str(arguments.get("answer_text") or "比明洞更生活方式，也更适合买小众品牌和美妆。")
        metadata = dict(arguments.get("metadata") or {})
        final_metadata = build_help_final_metadata(
            help_card_id=str(help_card.id),
            recommendation_card_id=str(arguments.get("recommendation_card_id") or "")
            or None,
            evidence_answer_ids=list(arguments.get("evidence_answer_ids") or []),
            decision_factor=str(arguments.get("decision_factor") or answer_text),
            confidence=metadata.get("confidence") or arguments.get("confidence"),
            retrieval_hit_ids=list(metadata.get("retrieval_hit_ids") or []),
            base=metadata,
        )
        existing = _existing_final_intent_answer(
            self.session,
            intent_id=intent.id,
            help_card_id=help_card.id,
            answer_text=answer_text,
        )
        if existing is not None:
            return {
                "id": str(existing.id),
                "status": "already_persisted",
                "source_type": existing.source_type,
                "source_ref_id": existing.source_ref_id,
                "confidence": existing.confidence,
            }

        final_card = help_card.final_recommendation_card
        answer_title = final_card.title if final_card is not None else "去圣水"
        confidence = (
            confidence_value(final_metadata.get("confidence"))
            or (final_card.confidence if final_card is not None else None)
            or 0.86
        )
        intent_answer = IntentAnswer(
            intent_id=intent.id,
            image_asset_id=image.id,
            answer_text=answer_text,
            intent_key=intent.key,
            intent_text=help_card.title,
            answer_title=answer_title,
            answer_summary=answer_text,
            constraints_json={
                "help_card_id": str(help_card.id),
                "title": help_card.title,
                "context": help_card.context_text,
                **(help_card.payload_json or {}),
            },
            source_type=HELP_FINAL_SOURCE_TYPE,
            source_ref_id=final_metadata["source_ref_id"],
            confidence=confidence,
            success_count=0,
            rejection_count=0,
            locale="zh-CN",
            tags_json=_help_final_tags(arguments),
            evidence_json=final_metadata,
            priority=30,
            is_active=True,
        )
        self.session.add(intent_answer)
        self.session.flush()

        if help_card.final_recommendation_card is not None:
            card = help_card.final_recommendation_card
            card.payload_json = {
                **(card.payload_json or {}),
                "intent_answer_id": str(intent_answer.id),
            }
        self.session.flush()
        return {
            "id": str(intent_answer.id),
            "status": "persisted",
            "source_type": intent_answer.source_type,
            "source_ref_id": intent_answer.source_ref_id,
            "confidence": intent_answer.confidence,
        }

    def _light_user(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        help_card = _get_help_card(self.session, arguments["help_card_id"])
        recommendation_card_id = arguments.get("recommendation_card_id")
        if recommendation_card_id is None and help_card.final_recommendation_card_id is not None:
            recommendation_card_id = str(help_card.final_recommendation_card_id)
        metadata = dict(arguments.get("metadata") or {})

        existing = self.session.scalar(
            select(LightEvent)
            .where(
                LightEvent.help_card_id == help_card.id,
                LightEvent.recommendation_card_id == uuid.UUID(str(recommendation_card_id)),
                LightEvent.type == "final_ready",
            )
            .order_by(LightEvent.created_at.desc())
        )
        if existing is not None:
            return {"id": str(existing.id), "status": "already_persisted", "type": existing.type}

        light = LightEvent(
            user_id=help_card.owner_user_id,
            conversation_id=help_card.conversation_id,
            question_id=help_card.question_id,
            help_card_id=help_card.id,
            recommendation_card_id=uuid.UUID(str(recommendation_card_id)),
            type=str(arguments.get("type") or "final_ready"),
            title=str(arguments.get("title") or "有人帮你选好了"),
            body=str(arguments.get("body") or f"{help_card.title} 有结果了。"),
            payload_json={
                **metadata,
                "card_id": str(recommendation_card_id),
                "help_card_id": str(help_card.id),
                "source": "pipi_finalize_graph",
            },
        )
        self.session.add(light)
        self.session.flush()
        return {"id": str(light.id), "status": "persisted", "type": light.type}


def _standard_finalize_tool_name(name: str) -> str:
    if name in {"finalize_recommendation", "finalize_help_card"}:
        return "finalize_help_card"
    if name in {"create_final_recommendation_card", "create_recommendation_card"}:
        return "create_recommendation_card"
    return name


def run_finalizer_once(
    ready_help_cards: Iterable[Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> FinalizerJobResult:
    """Convenience entry point for a scheduler or tests."""

    return PipiFinalizerJob(**kwargs).run_once(ready_help_cards)


def _state_from_help_card(card: Mapping[str, Any]) -> PipiFinalizeGraphState:
    help_card_id = str(card.get("id") or card.get("help_card_id") or "")
    state: PipiFinalizeGraphState = {"help_card_id": help_card_id}
    if card.get("question_id"):
        state["question_id"] = str(card["question_id"])
    if card.get("conversation_id"):
        state["conversation_id"] = str(card["conversation_id"])
    if card.get("user_id") or card.get("owner_user_id"):
        state["user_id"] = str(card.get("user_id") or card.get("owner_user_id"))
    state["help_card"] = {
        "id": help_card_id,
        "question_id": state.get("question_id", ""),
        "conversation_id": state.get("conversation_id", ""),
        "user_id": state.get("user_id", ""),
        "title": str(card.get("title") or ""),
        "context_text": str(card.get("context_text") or card.get("contextText") or ""),
        "answer_count": int(card.get("answer_count") or card.get("answerCount") or 0),
        "min_answers_required": int(
            card.get("min_answers_required") or card.get("minAnswersRequired") or 3
        ),
        "status": str(card.get("status") or "collecting"),
        "metadata": dict(card.get("metadata") or {}),
    }
    if "help_answers" in card or "answers" in card:
        raw_answers = card.get("help_answers") or card.get("answers") or []
        state["help_answers"] = [
            {
                "id": str(answer.get("id") or answer.get("answer_id") or ""),
                "help_card_id": str(
                    answer.get("help_card_id") or answer.get("helpCardId") or help_card_id
                ),
                "user_id": str(answer.get("user_id") or answer.get("answer_user_id") or ""),
                "text": str(answer.get("text") or answer.get("raw_text") or answer.get("rawText") or ""),
                "status": str(answer.get("status") or "collected"),
                "metadata": dict(answer.get("metadata") or {}),
            }
            for answer in raw_answers
        ]
    return state


def run_finalize_graph_for_help_card(
    session: Session,
    help_card_id: str | uuid.UUID,
) -> PipiFinalizeGraphState:
    """Run the DB-backed PipiFinalizeGraph for one persisted help card."""

    help_card = session.get(HelpCard, uuid.UUID(str(help_card_id)))
    if help_card is None:
        raise ValueError("help card not found")

    agent_run = AgentRun(
        conversation_id=help_card.conversation_id,
        turn_id=None,
        run_type="pipi_finalize",
        graph_name="PipiFinalizeGraph",
        model_provider="deterministic",
        model_name="deterministic-v0",
        status="running",
        input_json={"help_card_id": str(help_card.id)},
    )
    session.add(agent_run)
    session.flush()

    graph = PipiFinalizeGraph(
        repository=DbFinalizeRepository(session),
        retriever=DbFinalizeKnowledgeRetriever(
            session,
            agent_run=agent_run,
            help_card_id=help_card.id,
        ),
        tools=DbFinalizeToolInvoker(session, agent_run=agent_run),
    )
    state = graph.invoke(
        {
            "help_card_id": str(help_card.id),
            "question_id": str(help_card.question_id),
            "conversation_id": str(help_card.conversation_id),
            "user_id": str(help_card.owner_user_id),
            "agent_run_id": str(agent_run.id),
        }
    )
    agent_run.status = "succeeded" if state.get("status") != "failed" else "failed"
    agent_run.output_json = _safe_state(state)
    agent_run.finished_at = utcnow()
    return state


def _run_db_finalization_for_card(card: Mapping[str, Any]) -> PipiFinalizeGraphState:
    help_card_id = uuid.UUID(str(card.get("id") or card.get("help_card_id")))
    with session_scope() as session:
        return run_finalize_graph_for_help_card(session, help_card_id)


def _help_card_mapping(help_card: HelpCard) -> Mapping[str, Any]:
    return {
        "id": str(help_card.id),
        "question_id": str(help_card.question_id),
        "conversation_id": str(help_card.conversation_id),
        "owner_user_id": str(help_card.owner_user_id),
        "title": help_card.title,
        "context_text": help_card.context_text,
        "answer_count": help_card.answer_count,
        "min_answers_required": help_card.min_answers_required,
        "status": help_card.status,
        "metadata": help_card.payload_json or {},
    }


def _get_help_card(session: Session, help_card_id: Any) -> HelpCard:
    help_card = session.get(HelpCard, uuid.UUID(str(help_card_id)))
    if help_card is None:
        raise ValueError("help card not found")
    return help_card


def _assert_card_image(image: ImageAsset) -> None:
    if not image.displayable or image.verification_status != "verified" or image.is_ai_generated:
        raise ValueError("recommendation card images must be displayable, verified, and non-AI")


def _card_result(card: RecommendationCard, *, status: str) -> Mapping[str, Any]:
    return {
        "id": str(card.id),
        "card_id": str(card.id),
        "status": status,
        "title": card.title,
        "item": {"title": card.title},
        "decision_factor": {"text": card.reason},
        "image_asset_id": str(card.image_asset_id) if card.image_asset_id else None,
    }


def _existing_final_intent_answer(
    session: Session,
    *,
    intent_id: uuid.UUID,
    help_card_id: uuid.UUID,
    answer_text: str,
) -> IntentAnswer | None:
    candidates = session.scalars(
        select(IntentAnswer).where(
            IntentAnswer.intent_id == intent_id,
            IntentAnswer.answer_text == answer_text,
            IntentAnswer.source_type == "help_final",
            IntentAnswer.source_ref_id == str(help_card_id),
        )
    )
    for candidate in candidates:
        return candidate
    return None


def _help_final_tags(arguments: Mapping[str, Any]) -> list[str]:
    tags = [str(tag) for tag in arguments.get("tags") or [] if str(tag).strip()]
    tags.extend(["help_final", "korea", "seongsu"])
    return list(dict.fromkeys(tags))


def _safe_state(state: PipiFinalizeGraphState) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, (str, int, float, bool, type(None), list, dict)):
            safe[key] = value
    return safe


__all__ = [
    "DbFinalizeKnowledgeRetriever",
    "DbFinalizeRepository",
    "DbFinalizeToolInvoker",
    "DbFinalizerQueue",
    "FinalizerJobResult",
    "FinalizerQueue",
    "PipiFinalizerJob",
    "run_finalize_graph_for_help_card",
    "run_finalizer_once",
]
