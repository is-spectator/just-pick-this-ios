from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.models import AuthSession, Conversation, EmailLoginCode, User, UserDevice
from app.services.auth_tokens import hash_refresh_token
from app.services.runtime import session_scope, utcnow


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture(autouse=True)
def use_console_email_provider_for_auth_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth API tests need a deterministic code without sending real mail."""
    from app.services import auth_service

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    monkeypatch.setattr(auth_service, "_IP_HOURLY_LIMIT", 100000)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_email_code_login_creates_session_and_hashes_code(async_client: AsyncClient) -> None:
    email = _email("login")
    device_uid = f"pytest-auth-device-{uuid.uuid4().hex}"
    request = await async_client.post(
        "/v1/auth/request-code",
        json={"email": email, "device_uid": device_uid, "platform": "ios", "app_version": "0.1.0"},
    )
    assert request.status_code == 200, request.text
    body = request.json()
    code = body.get("dev_code")
    assert code and len(code) == 6

    with session_scope() as session:
        row = session.scalar(select(EmailLoginCode).where(EmailLoginCode.email == email))
        assert row is not None
        assert row.code_hash != code

    verify = await async_client.post(
        "/v1/auth/verify-code",
        json={"email": email, "code": code, "device_uid": device_uid},
    )
    assert verify.status_code == 200, verify.text
    tokens = verify.json()["tokens"]
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me = await async_client.get("/v1/auth/me", headers={"authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == email

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        assert session.scalar(select(UserDevice).where(UserDevice.device_uid == device_uid, UserDevice.user_id == user.id))
        assert session.scalar(
            select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(tokens["refresh_token"]))
        )


@pytest.mark.anyio
async def test_email_login_merges_device_conversations_into_account(async_client: AsyncClient) -> None:
    email = _email("merge")
    device_uid = f"pytest-merge-device-{uuid.uuid4().hex}"
    boot = await async_client.post("/v1/bootstrap", json={"device_uid": device_uid, "platform": "ios"})
    assert boot.status_code == 200, boot.text
    conversation_id = boot.json()["conversation_id"]

    code_response = await async_client.post("/v1/auth/request-code", json={"email": email, "device_uid": device_uid})
    code = code_response.json()["dev_code"]
    verify = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code, "device_uid": device_uid})
    assert verify.status_code == 200, verify.text
    access = verify.json()["tokens"]["access_token"]

    chat = await async_client.post(
        "/v1/chat/turn",
        headers={"authorization": f"Bearer {access}"},
        json={"conversation_id": conversation_id, "device_uid": device_uid, "message": "你好"},
    )
    assert chat.status_code == 200, chat.text

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        conversation = session.get(Conversation, uuid.UUID(conversation_id))
        assert conversation is not None
        assert conversation.user_id == user.id


@pytest.mark.anyio
async def test_update_me_sets_display_name(async_client: AsyncClient) -> None:
    email = _email("nickname")
    code_response = await async_client.post("/v1/auth/request-code", json={"email": email})
    code = code_response.json()["dev_code"]
    verify = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert verify.status_code == 200, verify.text
    access = verify.json()["tokens"]["access_token"]

    update = await async_client.patch(
        "/v1/auth/me",
        headers={"authorization": f"Bearer {access}"},
        json={"display_name": "  小皮同学  "},
    )
    assert update.status_code == 200, update.text
    assert update.json()["user"]["display_name"] == "小皮同学"

    me = await async_client.get("/v1/auth/me", headers={"authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["display_name"] == "小皮同学"

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.display_name == "小皮同学"


@pytest.mark.anyio
async def test_update_me_requires_authorization(async_client: AsyncClient) -> None:
    response = await async_client.patch("/v1/auth/me", json={"display_name": "小皮同学"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_delete_me_soft_deletes_account_and_revokes_sessions(async_client: AsyncClient) -> None:
    email = _email("delete")
    code_response = await async_client.post("/v1/auth/request-code", json={"email": email})
    code = code_response.json()["dev_code"]
    verify = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert verify.status_code == 200, verify.text
    tokens = verify.json()["tokens"]

    delete = await async_client.delete(
        "/v1/auth/me",
        headers={"authorization": f"Bearer {tokens['access_token']}"},
    )
    assert delete.status_code == 200, delete.text
    assert delete.json()["deleted"] is True

    me = await async_client.get("/v1/auth/me", headers={"authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 401
    refresh = await async_client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401

    with session_scope() as session:
        deleted_session = session.scalar(
            select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(tokens["refresh_token"]))
        )
        assert deleted_session is not None
        deleted = session.get(User, deleted_session.user_id)
        assert deleted is not None
        assert deleted.email is None
        assert deleted.status == "deleted"
        assert deleted.auth_provider == "deleted"
        assert deleted.display_name == "已删除用户"
        sessions = list(session.scalars(select(AuthSession).where(AuthSession.user_id == deleted.id)))
        assert sessions
        assert all(row.status == "revoked" for row in sessions)


@pytest.mark.anyio
async def test_refresh_rotates_and_logout_revokes_session(async_client: AsyncClient) -> None:
    email = _email("refresh")
    code_response = await async_client.post("/v1/auth/request-code", json={"email": email})
    code = code_response.json()["dev_code"]
    verify = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    tokens = verify.json()["tokens"]

    refresh = await async_client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 200, refresh.text
    new_tokens = refresh.json()["tokens"]
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    old_refresh = await async_client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert old_refresh.status_code == 401

    logout = await async_client.post("/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]})
    assert logout.status_code == 200
    revoked = await async_client.post("/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert revoked.status_code == 401


@pytest.mark.anyio
async def test_login_code_cannot_be_reused(async_client: AsyncClient) -> None:
    email = _email("reuse")
    code_response = await async_client.post("/v1/auth/request-code", json={"email": email})
    code = code_response.json()["dev_code"]
    ok = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert ok.status_code == 200, ok.text
    reused = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert reused.status_code == 400


@pytest.mark.anyio
async def test_request_code_rate_limit_cooldown(async_client: AsyncClient) -> None:
    email = _email("rate")
    first = await async_client.post("/v1/auth/request-code", json={"email": email})
    assert first.status_code == 200, first.text
    second = await async_client.post("/v1/auth/request-code", json={"email": email})
    assert second.status_code == 429


@pytest.mark.anyio
async def test_expired_code_is_rejected(async_client: AsyncClient) -> None:
    email = _email("expired")
    response = await async_client.post("/v1/auth/request-code", json={"email": email})
    code = response.json()["dev_code"]
    with session_scope() as session:
        row = session.scalar(select(EmailLoginCode).where(EmailLoginCode.email == email))
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
    verify = await async_client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert verify.status_code == 400
