from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

import app.agent.pipi_finalize_graph as pipi_finalize_graph
import app.services.help_feed as help_feed_service
from app.models import HelpCard, IntentAnswer, LightEvent, RecommendationCard
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, require_ready_response


async def _create_published_help_card(client: AsyncClient, *, case_name: str) -> tuple[dict[str, Any], str]:
    owner = await bootstrap(
        client,
        device_id=f"pytest-finalize-graph-owner-{case_name}-{uuid.uuid4()}",
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
    return owner, help_card_id


def _forbid_direct_finalize_help_card_now(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("API one-liner threshold must invoke PipiFinalizeGraph, not finalize_help_card_now")


def _archive_test_help_card(help_card_id: str | None) -> None:
    if help_card_id is None:
        return
    with session_scope() as session:
        help_card = session.get(HelpCard, uuid.UUID(help_card_id))
        if help_card is not None:
            help_card.status = "test_archived"


def _record_finalize_graph_invocations(monkeypatch: Any) -> list[dict[str, Any]]:
    graph_calls: list[dict[str, Any]] = []
    original_invoke = pipi_finalize_graph.PipiFinalizeGraph.invoke

    def recording_invoke(self: Any, state: dict[str, Any]) -> dict[str, Any]:
        graph_calls.append(dict(state))
        return original_invoke(self, state)

    monkeypatch.setattr(pipi_finalize_graph.PipiFinalizeGraph, "invoke", recording_invoke)
    monkeypatch.setattr(
        help_feed_service,
        "finalize_help_card_now",
        _forbid_direct_finalize_help_card_now,
        raising=False,
    )
    return graph_calls


async def _submit_three_one_liners_through_graph(
    client: AsyncClient,
    *,
    help_card_id: str,
    case_name: str,
    graph_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_body: dict[str, Any] = {}
    for index, text in enumerate(
        [
            "别去明洞当背景板，去圣水。",
            "圣水咖啡和小店密度高。",
            "预算不高也能逛圣水。",
        ],
        start=1,
    ):
        response = await client.post(
            f"/v1/help-cards/{help_card_id}/one-liner",
            json={
                "user_id": f"pytest-finalize-graph-answerer-{case_name}-{index}-{uuid.uuid4()}",
                "text": text,
            },
        )
        latest_body = require_ready_response(response)

    assert graph_calls, "answer threshold should invoke PipiFinalizeGraph"
    assert graph_calls[-1]["help_card_id"] == help_card_id
    assert latest_body["metadata"]["finalization_ready"] is True
    return latest_body


def test_one_liner_threshold_invokes_finalize_graph(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        graph_calls = _record_finalize_graph_invocations(monkeypatch)
        help_card_id: str | None = None
        try:
            _, help_card_id = await _create_published_help_card(async_client, case_name="invoke")

            await _submit_three_one_liners_through_graph(
                async_client,
                help_card_id=help_card_id,
                case_name="invoke",
                graph_calls=graph_calls,
            )
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)


def test_finalize_graph_creates_final_card(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        graph_calls = _record_finalize_graph_invocations(monkeypatch)
        help_card_id: str | None = None
        try:
            _, help_card_id = await _create_published_help_card(async_client, case_name="card")
            body = await _submit_three_one_liners_through_graph(
                async_client,
                help_card_id=help_card_id,
                case_name="card",
                graph_calls=graph_calls,
            )

            final_card_id = body["metadata"]["final_card_id"]
            assert final_card_id
            with session_scope() as session:
                help_card = session.get(HelpCard, uuid.UUID(help_card_id))
                final_card = session.get(RecommendationCard, uuid.UUID(final_card_id))

            assert help_card is not None
            assert final_card is not None
            assert str(help_card.final_recommendation_card_id) == final_card_id
            assert final_card.source == "pipi_finalized_from_help"
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)


def test_finalize_graph_saves_intent_answer(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        graph_calls = _record_finalize_graph_invocations(monkeypatch)
        help_card_id: str | None = None
        try:
            _, help_card_id = await _create_published_help_card(async_client, case_name="intent-answer")
            await _submit_three_one_liners_through_graph(
                async_client,
                help_card_id=help_card_id,
                case_name="intent-answer",
                graph_calls=graph_calls,
            )

            with session_scope() as session:
                intent_answers = [
                    answer
                    for answer in session.scalars(select(IntentAnswer))
                    if (answer.evidence_json or {}).get("help_card_id") == help_card_id
                ]

            assert intent_answers
            assert intent_answers[-1].evidence_json["source_type"] == "help_final"
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)


def test_finalize_graph_creates_light_event(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        graph_calls = _record_finalize_graph_invocations(monkeypatch)
        help_card_id: str | None = None
        try:
            _, help_card_id = await _create_published_help_card(async_client, case_name="light")
            await _submit_three_one_liners_through_graph(
                async_client,
                help_card_id=help_card_id,
                case_name="light",
                graph_calls=graph_calls,
            )

            with session_scope() as session:
                light_events = list(
                    session.scalars(
                        select(LightEvent).where(
                            LightEvent.help_card_id == uuid.UUID(help_card_id),
                            LightEvent.type == "final_ready",
                        )
                    )
                )

            assert light_events
        finally:
            _archive_test_help_card(help_card_id)

    run_async(scenario)
