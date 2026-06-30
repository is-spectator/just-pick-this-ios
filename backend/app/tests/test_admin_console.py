from __future__ import annotations

import uuid
from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import (
    AdminAuditLog,
    AgentAbilityConfig,
    AgentPromptConfig,
    AgentPromptConfigVersion,
    AgentRun,
    ContentReviewTask,
    ImageAsset,
    PromptReplayRun,
    Turn,
)
from app.services.ability_config import filter_enabled_ability_tools
from app.services.prompt_config import DEFAULT_PROMPT_CONFIGS
from app.services.runtime import session_scope


ADMIN_TOKEN = "unit-admin-token"


@pytest.fixture
def admin_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    get_settings.cache_clear()
    client = AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield client
    finally:
        anyio.run(client.aclose)
        get_settings.cache_clear()


def _headers(actor: str = "pytest-admin", *, role: str | None = None) -> dict[str, str]:
    headers = {"authorization": f"Bearer {ADMIN_TOKEN}", "x-admin-actor": actor}
    if role is not None:
        headers["x-admin-role"] = role
    return headers


@pytest.mark.anyio
async def test_admin_token_protects_console(admin_client: AsyncClient) -> None:
    missing = await admin_client.get("/admin/api/tables")
    assert missing.status_code == 401

    query_token = await admin_client.get("/admin/api/tables", params={"token": ADMIN_TOKEN})
    assert query_token.status_code == 401

    legacy_header = await admin_client.get("/admin/api/tables", headers={"x-admin-token": ADMIN_TOKEN})
    assert legacy_header.status_code == 401

    page = await admin_client.get("/admin/sessions", headers=_headers())
    assert page.status_code == 200
    assert "皮皮 Agent Admin" in page.text

    tables = await admin_client.get("/admin/api/tables", headers=_headers())
    assert tables.status_code == 200
    names = {item["name"] for item in tables.json()["items"]}
    assert {
        "conversations",
        "agent_runs",
        "agent_ability_configs",
        "agent_prompt_configs",
        "agent_prompt_config_versions",
        "prompt_replay_runs",
        "ops_metric_snapshots",
        "content_review_tasks",
        "admin_audit_logs",
    }.issubset(names)


@pytest.mark.anyio
async def test_admin_sessions_and_traces_are_queryable(admin_client: AsyncClient) -> None:
    device_id = f"admin-session-{uuid.uuid4()}"
    boot = await admin_client.post(
        "/v1/bootstrap",
        json={"device_id": device_id, "locale": "zh-CN", "timezone": "Asia/Shanghai"},
    )
    conversation_id = boot.json()["conversation_id"]
    await admin_client.post(
        "/v1/chat/turn",
        json={"conversation_id": conversation_id, "device_id": device_id, "message": "你好呀", "metadata": {}},
    )

    sessions = await admin_client.get(
        "/admin/api/sessions",
        params={"q": conversation_id, "page_size": 10},
        headers=_headers(),
    )
    assert sessions.status_code == 200
    assert any(item["id"] == conversation_id for item in sessions.json()["items"])

    intent_sessions = await admin_client.get(
        "/admin/api/sessions",
        params={"intent": "greeting", "page_size": 10},
        headers=_headers(),
    )
    assert intent_sessions.status_code == 200
    assert any(item["id"] == conversation_id for item in intent_sessions.json()["items"])

    detail = await admin_client.get(f"/admin/api/sessions/{conversation_id}", headers=_headers())
    assert detail.status_code == 200
    assert detail.json()["traces"]

    traces = await admin_client.get(
        "/admin/api/traces",
        params={"conversation_id": conversation_id},
        headers=_headers(),
    )
    assert traces.status_code == 200
    trace_id = traces.json()["items"][0]["id"]

    trace_detail = await admin_client.get(f"/admin/api/traces/{trace_id}", headers=_headers())
    assert trace_detail.status_code == 200
    assert trace_detail.json()["trace"]["output_json"]


@pytest.mark.anyio
async def test_admin_trace_detail_exposes_shadow_runtime_fields(admin_client: AsyncClient) -> None:
    device_id = f"admin-shadow-{uuid.uuid4()}"
    boot = await admin_client.post(
        "/v1/bootstrap",
        json={"device_id": device_id, "locale": "zh-CN", "timezone": "Asia/Shanghai"},
    )
    conversation_id = boot.json()["conversation_id"]
    await admin_client.post(
        "/v1/chat/turn",
        json={"conversation_id": conversation_id, "device_id": device_id, "message": "你好呀", "metadata": {}},
    )

    with session_scope() as session:
        run = session.scalar(
            select(AgentRun)
            .where(AgentRun.conversation_id == uuid.UUID(conversation_id))
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        assert run is not None
        output_json = dict(run.output_json or {})
        loop_trace = list(output_json.get("loop_trace") or [])
        loop_trace.append(
            {
                "iteration": 1,
                "event": "shadow_reasoner_result",
                "data": {
                    "status": "success",
                    "normalized_decision": {
                        "type": "tool",
                        "tool_name": "draft_help_card",
                        "tool_args": {"title": "小众美妆求一个"},
                    },
                },
            }
        )
        output_json["shadow_summary"] = {"enabled": True, "sampled": True, "calls": 1}
        output_json["loop_trace"] = loop_trace
        run.output_json = output_json
        trace_id = str(run.id)

    trace_detail = await admin_client.get(f"/admin/api/traces/{trace_id}", headers=_headers())
    assert trace_detail.status_code == 200
    trace_body = trace_detail.json()
    trace = trace_body["trace"]

    assert trace["shadow_summary"] == {"enabled": True, "sampled": True, "calls": 1}
    assert trace_body["shadow_summary"] == {"enabled": True, "sampled": True, "calls": 1}
    assert trace_body["shadow_decision_diffs"]
    assert trace_body["shadow_decision_diffs"][0]["mismatch"] is True
    assert [event["event"] for event in trace["shadow_events"]] == ["shadow_reasoner_result"]
    assert trace["shadow_decision_diffs"]
    first_diff = trace["shadow_decision_diffs"][0]
    assert first_diff["iteration"] == 1
    assert first_diff["matches"] is False
    assert first_diff["shadow_status"] == "success"
    assert first_diff["shadow_decision"]["tool_name"] == "draft_help_card"
    assert "tool_name" in first_diff["differences"]

    trace_list = await admin_client.get(
        "/admin/api/traces",
        params={"conversation_id": conversation_id},
        headers=_headers(),
    )
    assert trace_list.status_code == 200
    item = next(item for item in trace_list.json()["items"] if item["id"] == trace_id)
    assert item["shadow_summary"] == {"enabled": True, "sampled": True, "calls": 1}
    assert item["shadow_enabled"] is True
    assert item["shadow_event_count"] == 1
    assert item["shadow_mismatch_count"] >= 1


@pytest.mark.anyio
async def test_admin_table_crud_writes_audit_logs(admin_client: AsyncClient) -> None:
    key = f"admin-test-{uuid.uuid4()}"
    create_payload = {
        "key": key,
        "name": "Admin Test Intent",
        "description": "created by admin test",
        "examples_json": [],
        "is_active": True,
    }
    created = await admin_client.post(
        "/admin/api/tables/intents/rows",
        json=create_payload,
        headers=_headers(),
    )
    assert created.status_code == 200, created.text
    row = created.json()["item"]
    row_id = row["id"]

    listed = await admin_client.get(
        "/admin/api/tables/intents/rows",
        params={"q": key},
        headers=_headers(),
    )
    assert listed.status_code == 200
    assert any(item["id"] == row_id for item in listed.json()["items"])

    updated = await admin_client.patch(
        f"/admin/api/tables/intents/rows/{row_id}",
        json={"description": "updated by admin test"},
        headers=_headers(),
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["description"] == "updated by admin test"

    deleted = await admin_client.delete(
        f"/admin/api/tables/intents/rows/{row_id}",
        headers=_headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    with session_scope() as session:
        logs = list(
            session.scalars(
                select(AdminAuditLog)
                .where(AdminAuditLog.target_table == "intents", AdminAuditLog.target_record_id == row_id)
                .order_by(AdminAuditLog.created_at.asc())
            )
        )
        assert [log.action for log in logs][-3:] == ["insert", "update", "delete"]
        assert logs[-1].admin_actor == "pytest-admin"


@pytest.mark.anyio
async def test_admin_ability_center_configs_are_hot_updatable(admin_client: AsyncClient) -> None:
    actor = f"ability-admin-{uuid.uuid4()}"
    abilities = await admin_client.get("/admin/api/abilities", headers=_headers(actor))
    assert abilities.status_code == 200, abilities.text
    by_key = {item["key"]: item for item in abilities.json()["items"]}
    assert by_key["search_knowledge"]["runtime_status"] == "active"
    assert by_key["create_recommendation_card"]["runtime_registered"] is True

    custom_key = f"custom-skill-{uuid.uuid4()}"
    custom = await admin_client.put(
        f"/admin/api/abilities/{custom_key}",
        json={
            "name": "自定义技能",
            "ability_type": "custom_skill",
            "tool_name": None,
            "description": "运营先登记的技能，等待工程绑定执行器。",
            "enabled": True,
            "runtime_enabled": False,
            "trigger_intents_json": ["decision_request"],
            "input_schema_json": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_contract_json": {},
            "guardrails_json": {"runtime": "requires_engineering_binding"},
            "prompt_keys_json": [],
            "config_json": {"owner": "ops"},
            "notes": "pytest custom ability",
        },
        headers=_headers(actor, role="prompt_editor"),
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["hot_reload"] == "next_chat_turn"
    assert custom.json()["item"]["runtime_status"] == "draft"

    disabled = await admin_client.put(
        "/admin/api/abilities/draft_help_card",
        json={
            "name": "发起求一个",
            "ability_type": "builtin_tool",
            "tool_name": "draft_help_card",
            "description": "pytest temporarily disabled",
            "enabled": False,
            "runtime_enabled": False,
            "trigger_intents_json": ["decision_request", "help_request"],
            "input_schema_json": {},
            "output_contract_json": {},
            "guardrails_json": {},
            "prompt_keys_json": [],
            "config_json": {},
            "notes": "pytest disable",
        },
        headers=_headers(actor),
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["item"]["version"] >= 1

    with session_scope() as session:
        row = session.scalar(select(AgentAbilityConfig).where(AgentAbilityConfig.key == "draft_help_card"))
        assert row is not None
        assert row.enabled is False
        assert filter_enabled_ability_tools(session, ["search_knowledge", "draft_help_card"]) == ["search_knowledge"]

    reset = await admin_client.put(
        "/admin/api/abilities/draft_help_card",
        json={
            "name": "发起求一个",
            "ability_type": "builtin_tool",
            "tool_name": "draft_help_card",
            "description": "证据不足、无图或低置信时创建“求一个”。",
            "enabled": True,
            "runtime_enabled": True,
            "trigger_intents_json": ["decision_request", "help_request"],
            "input_schema_json": {},
            "output_contract_json": {},
            "guardrails_json": {},
            "prompt_keys_json": [],
            "config_json": {},
            "notes": "reset after pytest",
        },
        headers=_headers("ability-reset"),
    )
    assert reset.status_code == 200, reset.text


@pytest.mark.anyio
async def test_admin_prompt_configs_are_hot_updatable(admin_client: AsyncClient) -> None:
    with session_scope() as session:
        existing_log_ids = set(
            session.scalars(
                select(AdminAuditLog.id).where(
                    AdminAuditLog.admin_actor == "prompt-admin",
                    AdminAuditLog.target_table == "agent_prompt_configs",
                )
            )
        )

    prompts = await admin_client.get("/admin/api/prompts", headers=_headers("prompt-admin"))
    assert prompts.status_code == 200
    keys = {item["key"] for item in prompts.json()["items"]}
    assert "area_food_evidence_policy" in keys

    updated = await admin_client.put(
        "/admin/api/prompts/area_food_evidence_policy",
        json={
            "name": "到区域选店证据策略",
            "prompt_type": "evidence_policy",
            "content": "测试热更新：广东人优先粤菜。",
            "config_json": {
                "profile_cuisine_rules": [
                    {
                        "name": "pytest_cantonese",
                        "when_any": ["广东人"],
                        "search_keyword": "粤菜",
                        "display_food": "粤菜",
                        "decision_prefix": "你说自己是广东人，先按粤菜/清淡口味筛一遍。",
                        "prefer_terms": ["粤", "广东", "顺德"],
                        "reject_terms": ["长沙", "湘菜"],
                        "require_preferred_match": True,
                    }
                ]
            },
            "enabled": True,
            "notes": "pytest",
        },
        headers=_headers("prompt-admin"),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["hot_reload"] == "next_chat_turn"
    assert updated.json()["item"]["version"] >= 1
    updated_version = int(updated.json()["item"]["version"])

    with session_scope() as session:
        prompt_row = session.scalar(
            select(AgentPromptConfig).where(AgentPromptConfig.key == "area_food_evidence_policy")
        )
        assert prompt_row is not None
        version_row = session.scalar(
            select(AgentPromptConfigVersion).where(
                AgentPromptConfigVersion.prompt_key == "area_food_evidence_policy",
                AgentPromptConfigVersion.version == updated_version,
            )
        )
        assert version_row is not None
        assert version_row.content == "测试热更新：广东人优先粤菜。"
        assert version_row.updated_by == "prompt-admin"
        assert version_row.config_json["profile_cuisine_rules"][0]["name"] == "pytest_cantonese"

        logs = list(
            session.scalars(
                select(AdminAuditLog)
                .where(
                    AdminAuditLog.admin_actor == "prompt-admin",
                    AdminAuditLog.target_table == "agent_prompt_configs",
                    AdminAuditLog.id.not_in(existing_log_ids),
                )
                .order_by(AdminAuditLog.created_at.asc(), AdminAuditLog.id.asc())
            )
        )
        assert [log.action for log in logs] == ["list", "update"]

    default = DEFAULT_PROMPT_CONFIGS["area_food_evidence_policy"]
    await admin_client.put(
        "/admin/api/prompts/area_food_evidence_policy",
        json={
            "name": default["name"],
            "prompt_type": default["prompt_type"],
            "content": default["content"],
            "config_json": default["config_json"],
            "enabled": True,
            "notes": "reset after pytest",
        },
        headers=_headers("prompt-reset"),
    )


@pytest.mark.anyio
async def test_admin_prompt_versions_replay_and_rollback(admin_client: AsyncClient) -> None:
    key = f"pytest-policy-{uuid.uuid4()}"
    create_payload = {
        "name": "Pytest Policy",
        "prompt_type": "evidence_policy",
        "content": "v1 content",
        "config_json": {"profile_cuisine_rules": [{"name": "v1", "when_any": ["广东人"], "search_keyword": "粤菜"}]},
        "enabled": True,
        "notes": "create v1",
    }
    created = await admin_client.put(f"/admin/api/prompts/{key}", json=create_payload, headers=_headers("prompt-v1"))
    assert created.status_code == 200, created.text
    assert created.json()["item"]["version"] == 1

    updated = await admin_client.put(
        f"/admin/api/prompts/{key}",
        json={
            **create_payload,
            "content": "v2 content",
            "config_json": {"profile_cuisine_rules": [{"name": "v2", "when_any": ["广东人"], "search_keyword": "茶餐厅"}]},
            "notes": "update v2",
        },
        headers=_headers("prompt-v2"),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["version"] == 2

    versions = await admin_client.get(f"/admin/api/prompts/{key}/versions", headers=_headers("prompt-reader"))
    assert versions.status_code == 200
    version_items = versions.json()["items"]
    assert [item["version"] for item in version_items[:2]] == [2, 1]
    assert version_items[0]["content"] == "v2 content"
    assert version_items[1]["content"] == "v1 content"

    replay_actor = f"prompt-replay-{uuid.uuid4()}"
    with session_scope() as session:
        turn_ids_before = set(session.scalars(select(Turn.id)).all())

    replay = await admin_client.post(
        f"/admin/api/prompts/{key}/replay",
        json={
            "cases": [{"case_id": "manual", "message": "我是广东人，到了三里屯，吃什么"}],
            "candidate": {
                "content": "draft content",
                "config_json": {
                    "profile_cuisine_rules": [
                        {"name": "draft", "when_any": ["广东人"], "search_keyword": "顺德菜"}
                    ]
                },
            },
        },
        headers=_headers(replay_actor),
    )
    assert replay.status_code == 200, replay.text
    replay_item = replay.json()["item"]
    assert replay_item["status"] == "succeeded"
    assert replay_item["output_json"]["summary"]["case_count"] == 1
    assert replay_item["output_json"]["summary"]["changed_policy_count"] == 1

    with session_scope() as session:
        run = session.get(PromptReplayRun, uuid.UUID(replay_item["id"]))
        assert run is not None
        assert run.admin_actor == replay_actor
        assert set(session.scalars(select(Turn.id)).all()) == turn_ids_before
        replay_audit = session.scalar(
            select(AdminAuditLog).where(
                AdminAuditLog.admin_actor == replay_actor,
                AdminAuditLog.target_table == "prompt_replay_runs",
                AdminAuditLog.target_record_id == replay_item["id"],
            )
        )
        assert replay_audit is not None

    rollback = await admin_client.post(
        f"/admin/api/prompts/{key}/rollback",
        json={"version": 1, "notes": "rollback pytest"},
        headers=_headers("prompt-rollback"),
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["rolled_back_to_version"] == 1
    assert rollback.json()["item"]["version"] == 3
    assert rollback.json()["item"]["content"] == "v1 content"

    with session_scope() as session:
        history = session.scalars(
            select(AgentPromptConfigVersion)
            .where(AgentPromptConfigVersion.prompt_key == key)
            .order_by(AgentPromptConfigVersion.version.asc())
        ).all()
        assert [item.version for item in history] == [1, 2, 3]
        assert history[0].content == "v1 content"
        assert history[-1].change_reason == "rollback to v1"


@pytest.mark.anyio
async def test_admin_metrics_and_content_tasks_are_queryable(admin_client: AsyncClient) -> None:
    metrics_actor = f"metrics-reader-{uuid.uuid4()}"
    device_id = f"real-metrics-{uuid.uuid4()}"
    boot = await admin_client.post(
        "/v1/bootstrap",
        json={"device_id": device_id, "locale": "zh-CN", "timezone": "Asia/Shanghai"},
    )
    conversation_id = boot.json()["conversation_id"]
    await admin_client.post(
        "/v1/chat/turn",
        json={"conversation_id": conversation_id, "device_id": device_id, "message": "你好呀", "metadata": {}},
    )
    with session_scope() as session:
        image = ImageAsset(
            source_type="pytest",
            url=f"https://example.com/{uuid.uuid4()}.jpg",
            verified=False,
            verification_status="pending",
            is_ai_generated=False,
            displayable=False,
            metadata_json={"pytest": True},
        )
        session.add(image)
        session.flush()
        session.add(
            ContentReviewTask(
                task_type="pytest_review",
                status="open",
                priority=10,
                target_table="image_assets",
                target_record_id=str(image.id),
                title="pytest task",
                reason="pytest reason",
                payload_json={"pytest": True},
            )
        )

    overview = await admin_client.get("/admin/api/metrics/overview", headers=_headers(metrics_actor))
    assert overview.status_code == 200, overview.text
    assert overview.json()["users"]["total"] >= 1
    assert overview.json()["runtime"]["turns"] >= 1

    activity = await admin_client.get("/admin/api/metrics/activity", headers=_headers(metrics_actor))
    assert activity.status_code == 200
    assert activity.json()["items"]

    funnel = await admin_client.get("/admin/api/metrics/funnel", headers=_headers(metrics_actor))
    assert funnel.status_code == 200
    assert "recommendation_per_question" in funnel.json()["rates"]

    north_star = await admin_client.get("/admin/api/metrics/north-star", headers=_headers(metrics_actor))
    assert north_star.status_code == 200, north_star.text
    assert set(north_star.json()["rates"]) == {
        "accepted_card_rate",
        "followup_rate",
        "help_publish_rate",
        "one_liner_submit_rate",
        "reward_grant_rate",
    }

    failures = await admin_client.get("/admin/api/metrics/failures", headers=_headers(metrics_actor))
    assert failures.status_code == 200
    assert any(item["key"] == "pending_or_blocked_images" for item in failures.json()["items"])

    tasks = await admin_client.get("/admin/api/content/tasks", headers=_headers("content-reader"))
    assert tasks.status_code == 200, tasks.text
    task_types = {item["task_type"] for item in tasks.json()["items"]}
    assert {"pytest_review", "image_review"}.issubset(task_types)

    with session_scope() as session:
        logs = list(
            session.scalars(
                select(AdminAuditLog)
                .where(AdminAuditLog.admin_actor == metrics_actor)
                .order_by(AdminAuditLog.created_at.asc())
            )
        )
        assert [log.target_table for log in logs][-5:] == [
            "ops_metrics_overview",
            "ops_metrics_activity",
            "ops_metrics_funnel",
            "north_star_metrics",
            "ops_metrics_failures",
        ]


@pytest.mark.anyio
async def test_admin_roles_restrict_writes(admin_client: AsyncClient) -> None:
    key = f"viewer-denied-{uuid.uuid4()}"
    denied = await admin_client.put(
        f"/admin/api/prompts/{key}",
        json={"name": "Denied", "prompt_type": "policy", "content": "nope", "config_json": {}},
        headers=_headers("viewer", role="viewer"),
    )
    assert denied.status_code == 403

    metrics = await admin_client.get("/admin/api/metrics/overview", headers=_headers("viewer", role="viewer"))
    assert metrics.status_code == 200

    bad_target = await admin_client.post(
        "/admin/api/tables/content_review_tasks/rows",
        json={
            "task_type": "bad",
            "status": "open",
            "priority": 1,
            "target_table": "not_a_table",
            "target_record_id": "x",
            "title": "bad",
            "reason": "bad",
            "payload_json": {},
        },
        headers=_headers("content-ops", role="content_ops"),
    )
    assert bad_target.status_code == 400


@pytest.mark.anyio
async def test_admin_audit_log_table_is_read_only(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/admin/api/tables/admin_audit_logs/rows",
        json={"action": "insert"},
        headers=_headers(),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_read_operations_write_audit_logs(admin_client: AsyncClient) -> None:
    actor = f"pytest-read-{uuid.uuid4()}"
    response = await admin_client.get("/admin/api/tables", headers=_headers(actor))
    assert response.status_code == 200

    sessions = await admin_client.get(
        "/admin/api/sessions",
        params={"page_size": 1},
        headers=_headers(actor),
    )
    assert sessions.status_code == 200

    with session_scope() as session:
        logs = list(
            session.scalars(
                select(AdminAuditLog)
                .where(AdminAuditLog.admin_actor == actor)
                .order_by(AdminAuditLog.created_at.asc())
            )
        )
        assert [(log.action, log.target_table) for log in logs] == [
            ("list", "admin_tables"),
            ("list", "sessions"),
        ]
        assert logs[-1].request_json["page_size"] == 1
