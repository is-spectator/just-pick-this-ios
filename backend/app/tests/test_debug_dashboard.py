from __future__ import annotations

import pytest

from app.config import get_settings
from app.main import create_app

from .conftest import bootstrap, chat_turn, require_ready_response


@pytest.mark.anyio
async def test_debug_dashboard_exposes_sessions_and_trace_details(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DEBUG_ROUTES", "true")
    monkeypatch.setenv("DEBUG_DASHBOARD_TOKEN", "debug-token")
    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    async_client = AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        await bootstrap(async_client, device_id="debug-dashboard-session")
        turn_body = await chat_turn(
            async_client,
            message="我现在在大同喜晋道，不知道吃什么",
        )
    finally:
        pass
    conversation_id = turn_body["conversation_id"]
    headers = {"authorization": "Bearer debug-token"}

    page_response = await async_client.get("/debug/sessions", headers=headers)
    assert page_response.status_code == 200
    assert "皮皮 Trace Console" in page_response.text

    sessions_response = await async_client.get("/debug/api/sessions?limit=20", headers=headers)
    sessions_body = require_ready_response(sessions_response)
    session_summary = next(
        item for item in sessions_body["sessions"] if item["id"] == conversation_id
    )
    assert session_summary["counts"]["turns"] >= 2
    assert session_summary["counts"]["traces"] >= 1
    assert session_summary["counts"]["tools"] >= 1
    assert session_summary["counts"]["retrievals"] >= 1

    detail_response = await async_client.get(f"/debug/api/sessions/{conversation_id}", headers=headers)
    detail_body = require_ready_response(detail_response)

    await async_client.aclose()
    get_settings.cache_clear()

    assert [turn["role"] for turn in detail_body["turns"]][-2:] == ["user", "assistant"]
    assert detail_body["traces"]

    latest_trace = detail_body["traces"][-1]
    assert latest_trace["graph_name"] == "PipiChatGraph"
    assert latest_trace["intent"] == "decision_request"
    assert latest_trace["graph_nodes"]
    node_names = [node["name"] for node in latest_trace["graph_nodes"]]
    assert "build_context" in node_names
    assert "run_pipi_loop" in node_names
    assert latest_trace["tool_calls"]
    assert latest_trace["retrieval_runs"]
    assert latest_trace["retrieval_runs"][0]["hits"]
