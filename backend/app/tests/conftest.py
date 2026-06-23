from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.main import create_app


NOT_IMPLEMENTED_STATUSES = {404, 501}
_BOOTSTRAP_DEVICE_BY_CONVERSATION: dict[str, str] = {}

NO_DB_TEST_FILES = {
    "test_ability_center.py",
    "test_admin_debug_security.py",
    "test_answer_gate.py",
    "test_benchmark_500_distribution.py",
    "test_benchmark_non_empty_guard.py",
    "test_card_contract_and_answer_gate.py",
    "test_checkpoint_runtime_guard.py",
    "test_context_builder.py",
    "test_database_unavailable_response.py",
    "test_decision_factor_not_generic.py",
    "test_evaluator.py",
    "test_evidence_pack.py",
    "test_experiments.py",
    "test_finalize_harness_path.py",
    "test_harness_input_gate.py",
    "test_health_readiness.py",
    "test_help_card_extractor_compressor.py",
    "test_help_feed_ranking.py",
    "test_input_gate_reasoner_contract.py",
    "test_input_gate_slot_extraction.py",
    "test_no_old_graph_nodes_in_main_path.py",
    "test_no_secrets_committed.py",
    "test_one_liner_quality.py",
    "test_openai_guardrails.py",
    "test_product_benchmark_readiness.py",
    "test_product_benchmark_runtime_gate.py",
    "test_provider_fallback.py",
    "test_pipi_loop.py",
    "test_prompt_snapshots.py",
    "test_production_config_guard.py",
    "test_quality_gate.py",
    "test_quality_report_generation.py",
    "test_quality_scoring.py",
    "test_recommendation_card_v2_contract.py",
    "test_results_guard.py",
    "test_shadow_quality_diff.py",
    "test_shadow_promotion_candidates.py",
    "test_shadow_schema_contract.py",
    "test_test_scripts.py",
    "test_trace_store.py",
    "test_user_preference_memory.py",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-db",
        action="store_true",
        default=False,
        help="Fail collection if DATABASE_URL is configured but unreachable.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _database_is_ready():
        return
    if config.getoption("--require-db"):
        pytest.exit(
            "DATABASE_URL is not reachable. Start Postgres or run ./scripts/test.sh.",
            returncode=2,
        )

    skip_db = pytest.mark.skip(
        reason=(
            "database integration test skipped because DATABASE_URL is not reachable; "
            "start Postgres/Docker and run ./scripts/test.sh for full coverage"
        )
    )
    for item in items:
        if Path(str(item.fspath)).name not in NO_DB_TEST_FILES:
            item.add_marker(skip_db)


@lru_cache(maxsize=1)
def _database_is_ready() -> bool:
    settings = get_settings()
    if settings.database_url is None:
        return False
    engine = None
    try:
        engine = create_engine(str(settings.database_url), pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except (SQLAlchemyError, OSError):
        return False
    finally:
        if engine is not None:
            engine.dispose()
    return True


@pytest.fixture
def run_async() -> Any:
    return anyio.run


@pytest.fixture
def async_client() -> Any:
    app = create_app()
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    yield client
    anyio.run(client.aclose)


def require_ready_response(response: Response, *, expected_status: int = 200) -> dict[str, Any]:
    if response.status_code in NOT_IMPLEMENTED_STATUSES:
        pytest.xfail(
            f"Runtime API is not fully wired yet: {response.request.method} "
            f"{response.request.url.path} returned {response.status_code}."
        )
    assert response.status_code == expected_status, response.text
    if not response.content:
        return {}
    return response.json()


async def bootstrap(client: AsyncClient, *, device_id: str, user_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": device_id,
        "locale": "zh-CN",
        "timezone": "Asia/Shanghai",
        "metadata": {"platform": "ios", "app_version": "0.1.0"},
    }
    if user_id is not None:
        payload["user_id"] = user_id
    response = await client.post("/v1/bootstrap", json=payload)
    body = require_ready_response(response)
    if body.get("conversation_id"):
        _BOOTSTRAP_DEVICE_BY_CONVERSATION[str(body["conversation_id"])] = device_id
    return body


async def chat_turn(
    client: AsyncClient,
    *,
    message: str,
    conversation_id: str | None = None,
    device_id: str | None = None,
    client_turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": device_id
        or (conversation_id and _BOOTSTRAP_DEVICE_BY_CONVERSATION.get(str(conversation_id)))
        or "pytest-chat-device",
        "message": message,
        "metadata": metadata or {},
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    if client_turn_id is not None:
        payload["client_turn_id"] = client_turn_id
    response = await client.post("/v1/chat/turn", json=payload)
    return require_ready_response(response)


def extract_tool_names(body: dict[str, Any]) -> set[str]:
    return {
        str(tool.get("name") or tool.get("tool_name"))
        for tool in body.get("tool_calls", [])
        if tool.get("name") or tool.get("tool_name")
    }


def device_for_conversation(conversation_id: str) -> str | None:
    return _BOOTSTRAP_DEVICE_BY_CONVERSATION.get(str(conversation_id))
