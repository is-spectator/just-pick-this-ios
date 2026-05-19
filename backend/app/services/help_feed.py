from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.models import HelpAnswer, HelpCard
from app.services.chat import finalize_help_card_now
from app.services.runtime import (
    create_tool_call,
    ensure_user,
    resolve_request_user,
    serialize_help_card,
    session_scope,
)


def list_help_feed(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    del cursor
    with session_scope() as session:
        user = resolve_request_user(session, user_id=user_id, device_uid=device_uid)
        answered_ids: set[uuid.UUID] = set()
        if user is not None:
            answered_ids = set(
                session.scalars(select(HelpAnswer.help_card_id).where(HelpAnswer.answer_user_id == user.id))
            )
        query = (
            select(HelpCard)
            .where(HelpCard.status.in_(["published", "collecting"]))
            .order_by(HelpCard.answer_count.asc(), HelpCard.created_at.asc())
            .limit(limit)
        )
        if user is not None:
            query = query.where(HelpCard.owner_user_id != user.id)
        items = [card for card in session.scalars(query) if card.id not in answered_ids]
        return {"items": [serialize_help_card(card) for card in items], "next_cursor": None}


def create_one_liner(id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(id))
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        answer_user = ensure_user(
            session,
            device_uid=payload.get("device_id") or payload.get("user_id"),
            user_id=payload.get("user_id"),
        )
        if answer_user.id == help_card.owner_user_id:
            raise HTTPException(status_code=403, detail="owner_cannot_answer_own_help_card")
        if help_card.status not in {"published", "collecting", "draft"}:
            raise HTTPException(status_code=409, detail="help_card_not_collecting")
        existing = session.scalar(
            select(HelpAnswer).where(
                HelpAnswer.help_card_id == help_card.id,
                HelpAnswer.answer_user_id == answer_user.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="already_answered")

        answer = HelpAnswer(
            help_card_id=help_card.id,
            answer_user_id=answer_user.id,
            raw_text=payload["text"],
            normalized_text=payload["text"].strip(),
            status="submitted",
            reward_status="pending",
            evidence_json={"evidence_type": "human_one_liner"},
        )
        session.add(answer)
        help_card.answer_count += 1
        help_card.status = "collecting"
        help_card.question.status = "collecting_answers"
        session.flush()

        finalization_ready = help_card.answer_count >= help_card.min_answers_required
        final_card_id: str | None = None
        if finalization_ready:
            tool_call = create_tool_call(
                session,
                agent_run=_ensure_system_agent_run(session, help_card),
                turn=None,
                name="finalize_recommendation",
                arguments={"help_card_id": str(help_card.id), "trigger": "answer_threshold"},
            )
            final_card = finalize_help_card_now(session, help_card=help_card, agent_run=tool_call.agent_run, tool_call=tool_call)
            final_card_id = str(final_card.id)
            tool_call.status = "succeeded"
            tool_call.result_json = {"card_id": final_card_id}

        return {
            "help_card_id": str(help_card.id),
            "answer_id": str(answer.id),
            "accepted": True,
            "metadata": {
                "evidence_type": "human_one_liner",
                "answer_count": help_card.answer_count,
                "finalization_ready": finalization_ready,
                "final_card_id": final_card_id,
            },
        }


def _ensure_system_agent_run(session: Any, help_card: HelpCard) -> Any:
    from app.models import AgentRun

    run = AgentRun(
        conversation_id=help_card.conversation_id,
        turn_id=None,
        run_type="pipi_finalize",
        graph_name="PipiFinalizeGraph",
        model_provider="deterministic",
        model_name="deterministic-v0",
        status="succeeded",
        input_json={"help_card_id": str(help_card.id)},
        output_json={},
    )
    session.add(run)
    session.flush()
    return run
