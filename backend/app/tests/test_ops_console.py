from __future__ import annotations

import uuid
from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.agent.pipi_loop import PipiLoop
from app.agent.schemas import PipiLoopResult
from app.config import get_settings
from app.main import create_app
from app.models import AdminAuditLog, AgentRun, PromptAssignment, PromptAuditLog, PromptPublishEvent, PromptVersion
from app.ops.prompt_registry import PromptRegistry
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


ADMIN_TOKEN = "unit-ops-token"


@pytest.fixture
def ops_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    get_settings.cache_clear()
    PromptRegistry.invalidate()
    client = AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield client
    finally:
        anyio.run(client.aclose)
        _cleanup_prompt_editor_rows("pytest-prompt-editor")
        PromptRegistry.invalidate()
        get_settings.cache_clear()


def _headers(actor: str = "pytest-ops") -> dict[str, str]:
    return {"authorization": f"Bearer {ADMIN_TOKEN}", "x-admin-actor": actor}


def _cleanup_prompt_editor_rows(actor: str) -> None:
    with session_scope() as session:
        test_versions = list(session.scalars(select(PromptVersion).where(PromptVersion.created_by == actor)))
        test_ids = {version.id for version in test_versions}
        if test_ids:
            for assignment in list(
                session.scalars(select(PromptAssignment).where(PromptAssignment.active_version_id.in_(test_ids)))
            ):
                fallback = session.scalar(
                    select(PromptVersion)
                    .where(
                        PromptVersion.template_id.in_({version.template_id for version in test_versions}),
                        PromptVersion.created_by != actor,
                    )
                    .order_by(PromptVersion.version.asc())
                    .limit(1)
                )
                if fallback is not None:
                    assignment.active_version_id = fallback.id
        for row in list(session.scalars(select(PromptPublishEvent).where(PromptPublishEvent.published_by == actor))):
            session.delete(row)
        if test_ids:
            for row in list(session.scalars(select(PromptAuditLog).where(PromptAuditLog.version_id.in_(test_ids)))):
                session.delete(row)
        for row in list(session.scalars(select(PromptAuditLog).where(PromptAuditLog.actor == actor))):
            session.delete(row)
        for row in list(session.scalars(select(AdminAuditLog).where(AdminAuditLog.admin_actor == actor))):
            session.delete(row)
        for version in test_versions:
            session.delete(version)


@pytest.mark.anyio
async def test_ops_token_protects_console_and_apis(ops_client: AsyncClient) -> None:
    missing = await ops_client.get("/ops/api/agent/graph")
    assert missing.status_code == 401

    query_token = await ops_client.get("/ops/api/agent/graph", params={"token": ADMIN_TOKEN})
    assert query_token.status_code == 401

    legacy_header = await ops_client.get("/ops/api/agent/graph", headers={"x-admin-token": ADMIN_TOKEN})
    assert legacy_header.status_code == 401

    page = await ops_client.get("/ops", headers=_headers())
    assert page.status_code == 200
    assert "Pipi Ops" in page.text

    graph = await ops_client.get("/ops/api/agent/graph", headers=_headers())
    assert graph.status_code == 200


@pytest.mark.anyio
async def test_ops_agent_flow_exposes_prompt_scopes(ops_client: AsyncClient) -> None:
    response = await ops_client.get("/ops/api/agent/graph", headers=_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    nodes = {item["id"]: item for item in body["nodes"]}

    assert {"input_gate", "pipi_loop", "reasoner", "ability_center", "answer_gate"}.issubset(nodes)
    assert nodes["reasoner"]["prompt_key"] == "reasoner.system"
    assert nodes["reasoner"]["active_prompt_version"]["version"] >= 1
    assert nodes["ability_center"]["prompt_key"] == "reasoner.tool_policy"
    assert any(edge["source"] == "reasoner" and edge["target"] == "ability_center" for edge in body["edges"])


@pytest.mark.anyio
async def test_ops_prompt_center_draft_dry_run_publish_and_rollback(ops_client: AsyncClient) -> None:
    prompt_key = "reasoner.system"
    detail = await ops_client.get(f"/ops/api/prompts/{prompt_key}", headers=_headers())
    assert detail.status_code == 200, detail.text
    initial_active = detail.json()["active_version"]

    draft = await ops_client.post(
        f"/ops/api/prompts/{prompt_key}/draft",
        json={
            "base_version_id": initial_active["id"],
            "content": f"{initial_active['content']}\n\n测试发布链路 {uuid.uuid4()}",
        },
        headers=_headers("pytest-prompt-editor"),
    )
    assert draft.status_code == 200, draft.text
    draft_version = draft.json()["item"]
    assert draft_version["status"] == "draft"

    blocked_publish = await ops_client.post(
        f"/ops/api/prompts/{prompt_key}/publish",
        json={"version_id": draft_version["id"]},
        headers=_headers("pytest-prompt-editor"),
    )
    assert blocked_publish.status_code == 409

    dry_run = await ops_client.post(
        f"/ops/api/prompts/{prompt_key}/dry-run",
        json={"version_id": draft_version["id"]},
        headers=_headers("pytest-prompt-editor"),
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["passed"] is True

    published = await ops_client.post(
        f"/ops/api/prompts/{prompt_key}/publish",
        json={"version_id": draft_version["id"]},
        headers=_headers("pytest-prompt-editor"),
    )
    assert published.status_code == 200, published.text
    assert published.json()["item"]["status"] == "published"
    assert published.json()["hot_reload"] == "next_chat_turn"

    after_publish = await ops_client.get(f"/ops/api/prompts/{prompt_key}", headers=_headers())
    assert after_publish.status_code == 200
    assert after_publish.json()["assignment"]["active_version_id"] == draft_version["id"]

    rollback = await ops_client.post(
        f"/ops/api/prompts/{prompt_key}/rollback",
        json={"version_id": initial_active["id"]},
        headers=_headers("pytest-prompt-editor"),
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["item"]["id"] == initial_active["id"]

    with session_scope() as session:
        assert session.scalar(
            select(PromptPublishEvent).where(PromptPublishEvent.to_version_id == uuid.UUID(draft_version["id"]))
        )
        audit_actions = [
            row.action
            for row in session.scalars(
                select(PromptAuditLog)
                .where(PromptAuditLog.prompt_key == prompt_key)
                .order_by(PromptAuditLog.created_at.asc())
            )
        ]
        assert {"draft", "dry_run", "publish", "rollback"}.issubset(audit_actions)
        admin_actions = [
            row.action
            for row in session.scalars(
                select(AdminAuditLog)
                .where(AdminAuditLog.target_table == "ops_prompts")
                .order_by(AdminAuditLog.created_at.asc())
            )
        ]
        assert {"draft", "dry_run", "publish", "rollback"}.issubset(admin_actions)


@pytest.mark.anyio
async def test_ops_trace_replay_exposes_recorded_prompt_versions(
    ops_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(self: PipiLoop, state: Any) -> PipiLoopResult:
        return PipiLoopResult(
            message="ops trace response",
            iterations=1,
            finish_reason="answer",
            trace=[
                {
                    "iteration": 1,
                    "event": "reasoner_decision",
                    "data": {"type": "answer", "message": "ops trace response"},
                },
                {
                    "iteration": 1,
                    "event": "answer_gate_result",
                    "data": {"passed": True},
                },
            ],
            state=state.model_dump(mode="json"),
        )

    monkeypatch.setattr(PipiLoop, "run", fake_run)

    boot = await bootstrap(ops_client, device_id=f"ops-trace-{uuid.uuid4()}")
    await chat_turn(
        ops_client,
        conversation_id=boot["conversation_id"],
        message="我在大同喜晋道，吃什么",
    )

    with session_scope() as session:
        run = session.scalar(
            select(AgentRun)
            .where(AgentRun.conversation_id == uuid.UUID(boot["conversation_id"]))
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        assert run is not None
        assert (run.input_json or {})["prompt_versions"]["reasoner.system"]["version"] >= 1
        trace_id = str(run.id)

    trace = await ops_client.get(f"/ops/api/traces/{trace_id}", headers=_headers())
    assert trace.status_code == 200, trace.text
    body = trace.json()
    assert body["prompt_versions"]["reasoner.system"]["version"] >= 1
    assert [event["event"] for event in body["loop_trace"]] == [
        "reasoner_decision",
        "answer_gate_result",
    ]


@pytest.mark.anyio
async def test_ops_prompt_list_seeds_v0_scopes(ops_client: AsyncClient) -> None:
    response = await ops_client.get("/ops/api/prompts", headers=_headers())
    assert response.status_code == 200, response.text
    prompt_keys = {item["template"]["prompt_key"] for item in response.json()["items"]}
    assert {
        "input_gate.system",
        "context_builder.policy",
        "reasoner.system",
        "reasoner.tool_policy",
        "evaluator.system",
        "answer_gate.system",
        "help_card_extractor.system",
        "finalizer.system",
        "shadow_reasoner.system",
    }.issubset(prompt_keys)
