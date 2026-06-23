from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.models import User
from app.services import runtime
from app.services.runtime import session_scope


def test_session_scope_does_not_seed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_SEED_ON_REQUEST", "false")
    get_settings.cache_clear()
    called = {"count": 0}

    def fail_seed(_session: object) -> None:
        called["count"] += 1
        raise AssertionError("seed should not run")

    monkeypatch.setattr(runtime, "ensure_seed_data", fail_seed)
    with session_scope():
        pass
    assert called["count"] == 0
    get_settings.cache_clear()


def test_session_scope_can_seed_when_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_SEED_ON_REQUEST", "true")
    get_settings.cache_clear()
    called = {"count": 0}

    def count_seed(_session: object) -> None:
        called["count"] += 1

    monkeypatch.setattr(runtime, "ensure_seed_data", count_seed)
    with session_scope():
        pass
    assert called["count"] == 1
    get_settings.cache_clear()


def test_bootstrap_requires_device_uid() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/v1/bootstrap", json={"platform": "ios"})
    assert response.status_code == 400


def test_chat_turn_requires_device_uid() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/v1/chat/turn", json={"message": "你好"})
    assert response.status_code == 400


def test_chat_turn_rejects_conversation_owned_by_other_device() -> None:
    owner_device = f"owner-{uuid.uuid4()}"
    with TestClient(create_app()) as client:
        boot = client.post("/v1/bootstrap", json={"device_uid": owner_device})
        assert boot.status_code == 200
        conversation_id = boot.json()["conversation_id"]
        response = client.post(
            "/v1/chat/turn",
            json={
                "conversation_id": conversation_id,
                "device_uid": f"other-{uuid.uuid4()}",
                "message": "你好",
            },
        )
    assert response.status_code == 403


def test_chat_turn_accepts_existing_user_id_without_shadow_device() -> None:
    device_uid = f"user-id-device-{uuid.uuid4()}"
    with TestClient(create_app()) as client:
        boot = client.post("/v1/bootstrap", json={"device_uid": device_uid})
        assert boot.status_code == 200
        user_id = boot.json()["user"]["id"]
        conversation_id = boot.json()["conversation_id"]
        response = client.post(
            "/v1/chat/turn",
            json={"conversation_id": conversation_id, "user_id": user_id, "message": "你好"},
        )
        assert response.status_code == 200, response.text

    with session_scope() as session:
        assert session.query(User).filter(User.device_uid == user_id).count() == 0
