from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.models import AuthSession, User
from app.services.runtime import utcnow


_DEV_SECRET = "dev-auth-secret-not-for-production"


def create_access_token(user: User, auth_session: AuthSession) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    expires_in = int(settings.access_token_ttl_seconds)
    payload = {
        "iss": "just-pick-this-ios-backend",
        "sub": str(user.id),
        "sid": str(auth_session.id),
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "typ": "access",
    }
    return _encode_jwt(payload), expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid access token")
    signing_input = f"{parts[0]}.{parts[1]}".encode()
    expected = _b64url(hmac.new(_secret_bytes(), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(expected, parts[2]):
        raise HTTPException(status_code=401, detail="invalid access token")
    try:
        payload = json.loads(_b64url_decode(parts[1]).decode())
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid access token") from exc
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="invalid access token")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(utcnow().timestamp()):
        raise HTTPException(status_code=401, detail="access token expired")
    return payload


def bearer_token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    return token.strip()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def generate_login_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_login_code(email: str, code: str) -> str:
    message = f"{email.strip().lower()}:{code.strip()}".encode()
    return hmac.new(_secret_bytes(), message, hashlib.sha256).hexdigest()


def new_email_device_uid() -> str:
    return f"email-{uuid.uuid4()}"


def _encode_jwt(payload: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = _b64url(hmac.new(_secret_bytes(), signing_input, hashlib.sha256).digest())
    return f"{header_b64}.{payload_b64}.{signature}"


def _secret_bytes() -> bytes:
    settings = get_settings()
    if settings.jwt_secret is not None:
        return settings.jwt_secret.get_secret_value().encode()
    return _DEV_SECRET.encode()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode())
