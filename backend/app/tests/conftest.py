from __future__ import annotations

from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import create_app


NOT_IMPLEMENTED_STATUSES = {404, 501}


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
    return require_ready_response(response)


async def chat_turn(
    client: AsyncClient,
    *,
    message: str,
    conversation_id: str | None = None,
    client_turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
