"""Deterministic finalizer job V0.

This module coordinates ready help cards with PipiFinalizeGraph without owning
database queries, persistence, or scheduler setup.  Those concerns can be
plugged in through the small queue/repository/tool interfaces.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol, TypedDict, runtime_checkable

from app.agent.pipi_finalize_graph import (
    FinalizeRepository,
    KnowledgeRetriever,
    PipiFinalizeGraph,
    PipiFinalizeGraphState,
    ToolInvoker,
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


def run_finalizer_once(
    ready_help_cards: Iterable[Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> FinalizerJobResult:
    """Convenience entry point for a scheduler or tests."""

    return PipiFinalizerJob(**kwargs).run_once(ready_help_cards)


def _state_from_help_card(card: Mapping[str, Any]) -> PipiFinalizeGraphState:
    help_card_id = str(card.get("id") or card.get("help_card_id") or "")
    state: PipiFinalizeGraphState = {"help_card_id": help_card_id}
    if card.get("conversation_id"):
        state["conversation_id"] = str(card["conversation_id"])
    if card.get("user_id") or card.get("owner_user_id"):
        state["user_id"] = str(card.get("user_id") or card.get("owner_user_id"))
    state["help_card"] = {
        "id": help_card_id,
        "conversation_id": state.get("conversation_id", ""),
        "user_id": state.get("user_id", ""),
        "title": str(card.get("title") or ""),
        "context_text": str(card.get("context_text") or card.get("contextText") or ""),
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


__all__ = ["FinalizerJobResult", "FinalizerQueue", "PipiFinalizerJob", "run_finalizer_once"]
