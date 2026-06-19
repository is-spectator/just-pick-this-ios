from __future__ import annotations

import inspect
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

import app.agent.pipi_chat_graph as pipi_chat_graph
from app.agent.pipi_loop import PipiLoop
from app.models import AgentRun, HelpCard
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn, extract_tool_names


def _agent_output_for_turn(user_turn_id: str) -> dict[str, Any]:
    with session_scope() as session:
        agent_run = session.scalar(
            select(AgentRun).where(AgentRun.turn_id == uuid.UUID(user_turn_id))
        )
        assert agent_run is not None
        return dict(agent_run.output_json or {})


def _archive_help_cards_from_body(body: dict[str, Any]) -> None:
    help_card_ids = [card["id"] for card in body.get("help_cards", []) if card.get("id")]
    if not help_card_ids:
        return
    with session_scope() as session:
        for help_card_id in help_card_ids:
            help_card = session.get(HelpCard, uuid.UUID(help_card_id))
            if help_card is not None:
                help_card.status = "test_archived"


async def _run_chat(client: AsyncClient, *, case_name: str, message: str) -> dict[str, Any]:
    boot = await bootstrap(
        client,
        device_id=f"pytest-evidence-evaluator-{case_name}-{uuid.uuid4()}",
    )
    return await chat_turn(
        client,
        conversation_id=boot["conversation_id"],
        message=message,
    )


def test_evidence_evaluator_allows_strong_match(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    graph_source = inspect.getsource(pipi_chat_graph.build_pipi_chat_graph)
    loop_source = inspect.getsource(PipiLoop.run)
    assert 'add_node("run_pipi_loop"' in graph_source
    assert 'add_node("evaluate_evidence"' not in graph_source
    assert "evaluate_tool_result" in loop_source

    async def scenario() -> None:
        body = await _run_chat(
            async_client,
            case_name="strong-match",
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )
        output = _agent_output_for_turn(body["user_turn_id"])
        evaluation = output.get("evidence_evaluation")

        assert evaluation is not None
        assert evaluation["can_recommend"] is True
        assert evaluation["confidence"] >= 0.7
        assert evaluation["missing_requirements"] == []
        assert body["cards"]

    run_async(scenario)


def test_evidence_evaluator_blocks_weak_match(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        body = await _run_chat(
            async_client,
            case_name="weak-match",
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )
        try:
            output = _agent_output_for_turn(body["user_turn_id"])
            evaluation = output.get("evidence_evaluation")

            assert evaluation is not None
            assert evaluation["can_recommend"] is False
            assert evaluation["confidence"] < 0.7
            assert evaluation["missing_requirements"]
            assert "draft_help_card" in extract_tool_names(body)
            assert body["cards"] == []
            assert body["help_cards"]
        finally:
            _archive_help_cards_from_body(body)

    run_async(scenario)


def test_evidence_evaluator_output_is_persisted(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        body = await _run_chat(
            async_client,
            case_name="persisted-output",
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        output = _agent_output_for_turn(body["user_turn_id"])
        assert "evidence_evaluation" in output
        evaluation = output["evidence_evaluation"]
        assert set(evaluation) >= {
            "can_recommend",
            "confidence",
            "missing_requirements",
            "reason",
        }

    run_async(scenario)
