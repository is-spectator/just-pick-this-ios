from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthAuditLog, AuthSession, EmailLoginCode, User
from app.schemas.auth import AuthUser, TokenPair
from app.services.auth_tokens import (
    bearer_token_from_header,
    create_access_token,
    decode_access_token,
    generate_login_code,
    generate_refresh_token,
    hash_login_code,
    hash_refresh_token,
    new_email_device_uid,
)
from app.services.email_service import email_service
from app.services.runtime import utcnow
from app.services.user_merge_service import merge_device_user_into_email_user


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CODE_TTL_SECONDS = 600
_COOLDOWN_SECONDS = 60
_EMAIL_HOURLY_LIMIT = 5
_IP_HOURLY_LIMIT = 20


def request_login_code(
    session: Session,
    *,
    email: str,
    device_uid: str | None,
    platform: str | None = None,
    app_version: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    normalized_email = normalize_email(email)
    _enforce_code_rate_limits(
        session,
        email=normalized_email,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    code = generate_login_code()
    now = utcnow()
    row = EmailLoginCode(
        email=normalized_email,
        code_hash=hash_login_code(normalized_email, code),
        purpose="login",
        status="pending",
        max_attempts=5,
        expires_at=now + timedelta(seconds=_CODE_TTL_SECONDS),
        sent_at=now,
        request_ip=ip_address,
        user_agent=user_agent,
        device_uid=device_uid,
    )
    session.add(row)
    send_result = email_service.send_login_code(normalized_email, code)
    if not send_result.ok:
        row.status = "send_failed"
        _audit(
            session,
            action="request_code_failed",
            email=normalized_email,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"provider": send_result.provider, "error": send_result.error},
        )
        raise HTTPException(status_code=502, detail="email_send_failed")

    _audit(
        session,
        action="request_code",
        email=normalized_email,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={
            "provider": send_result.provider,
            "device_uid_present": bool(device_uid),
            "platform": platform,
            "app_version": app_version,
        },
    )
    response: dict[str, Any] = {
        "ok": True,
        "expires_in": _CODE_TTL_SECONDS,
        "cooldown_seconds": _COOLDOWN_SECONDS,
    }
    settings = get_settings()
    if settings.app_env in {"development", "test"} and settings.email_provider == "console":
        response["dev_code"] = code
    return response


def verify_login_code(
    session: Session,
    *,
    email: str,
    code: str,
    device_uid: str | None,
    platform: str | None = None,
    app_version: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    normalized_email = normalize_email(email)
    row = session.scalar(
        select(EmailLoginCode)
        .where(EmailLoginCode.email == normalized_email, EmailLoginCode.purpose == "login")
        .order_by(EmailLoginCode.created_at.desc())
        .limit(1)
    )
    if row is None or row.status not in {"pending", "sent"}:
        _audit(session, action="verify_failed", email=normalized_email, ip_address=ip_address, user_agent=user_agent)
        raise HTTPException(status_code=400, detail="invalid_or_expired_code")
    now = utcnow()
    if row.expires_at < now:
        row.status = "expired"
        _audit(session, action="verify_failed", email=normalized_email, ip_address=ip_address, user_agent=user_agent, metadata={"reason": "expired"})
        raise HTTPException(status_code=400, detail="invalid_or_expired_code")
    if row.attempts >= row.max_attempts:
        row.status = "blocked"
        _audit(session, action="verify_blocked", email=normalized_email, ip_address=ip_address, user_agent=user_agent)
        raise HTTPException(status_code=429, detail="too_many_attempts")
    if row.code_hash != hash_login_code(normalized_email, code):
        row.attempts += 1
        if row.attempts >= row.max_attempts:
            row.status = "blocked"
        _audit(
            session,
            action="verify_failed",
            email=normalized_email,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"attempts": row.attempts},
        )
        raise HTTPException(status_code=400, detail="invalid_or_expired_code")

    user = _get_or_create_email_user(
        session,
        email=normalized_email,
        platform=platform,
        app_version=app_version,
    )
    merge_result = merge_device_user_into_email_user(
        session,
        device_uid=device_uid,
        email_user=user,
        platform=platform,
        app_version=app_version,
    )
    row.status = "used"
    row.used_at = now
    user.email_verified_at = user.email_verified_at or now
    user.last_login_at = now
    user.last_seen_at = now
    user.auth_provider = "email"
    user.status = "active"
    session.flush()

    refresh_token = generate_refresh_token()
    auth_session = AuthSession(
        user_id=user.id,
        device_uid=device_uid,
        refresh_token_hash=hash_refresh_token(refresh_token),
        status="active",
        expires_at=now + timedelta(days=get_settings().refresh_token_ttl_days),
        last_seen_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(auth_session)
    session.flush()
    access_token, expires_in = create_access_token(user, auth_session)
    _audit(
        session,
        user=user,
        email=normalized_email,
        action="verify_success",
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"merge": merge_result, "auth_session_id": str(auth_session.id)},
    )
    return {
        "user": _auth_user(user),
        "tokens": _token_pair(access_token, refresh_token, expires_in),
    }


def refresh_tokens(
    session: Session,
    *,
    refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    auth_session = _active_session_by_refresh_token(session, refresh_token)
    user = session.get(User, auth_session.user_id)
    if user is None or user.status not in {"active", "merged"}:
        raise HTTPException(status_code=401, detail="invalid refresh token")
    new_refresh = generate_refresh_token()
    auth_session.refresh_token_hash = hash_refresh_token(new_refresh)
    auth_session.expires_at = utcnow() + timedelta(days=get_settings().refresh_token_ttl_days)
    auth_session.last_seen_at = utcnow()
    auth_session.ip_address = ip_address or auth_session.ip_address
    auth_session.user_agent = user_agent or auth_session.user_agent
    user.last_seen_at = utcnow()
    access_token, expires_in = create_access_token(user, auth_session)
    _audit(session, user=user, email=user.email, action="refresh", ip_address=ip_address, user_agent=user_agent)
    return {"tokens": _token_pair(access_token, new_refresh, expires_in)}


def logout(
    session: Session,
    *,
    refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    try:
        auth_session = _active_session_by_refresh_token(session, refresh_token)
    except HTTPException:
        return {"ok": True}
    auth_session.status = "revoked"
    auth_session.revoked_at = utcnow()
    user = session.get(User, auth_session.user_id)
    _audit(session, user=user, email=user.email if user else None, action="logout", ip_address=ip_address, user_agent=user_agent)
    return {"ok": True}


def current_user_from_authorization(
    session: Session,
    authorization: str | None,
) -> User | None:
    token = bearer_token_from_header(authorization)
    if token is None:
        return None
    claims = decode_access_token(token)
    try:
        user_id = uuid.UUID(str(claims["sub"]))
        session_id = uuid.UUID(str(claims["sid"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid access token") from exc
    auth_session = session.get(AuthSession, session_id)
    if (
        auth_session is None
        or auth_session.user_id != user_id
        or auth_session.status != "active"
        or auth_session.expires_at < utcnow()
    ):
        raise HTTPException(status_code=401, detail="invalid access token")
    user = session.get(User, user_id)
    if user is None or user.status not in {"active", "merged"}:
        raise HTTPException(status_code=401, detail="invalid access token")
    auth_session.last_seen_at = utcnow()
    user.last_seen_at = utcnow()
    return user


def me_from_authorization(session: Session, authorization: str | None) -> dict[str, Any]:
    user = current_user_from_authorization(session, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Authorization required")
    return {"user": _auth_user(user), "metadata": {"auth_provider": user.auth_provider}}


def update_me_from_authorization(
    session: Session,
    authorization: str | None,
    *,
    display_name: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    user = current_user_from_authorization(session, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Authorization required")
    nickname = _normalize_display_name(display_name)
    old_display_name = user.display_name
    user.display_name = nickname
    user.last_seen_at = utcnow()
    _audit(
        session,
        user=user,
        email=user.email,
        action="update_profile",
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={
            "fields": ["display_name"],
            "old_display_name": old_display_name,
            "new_display_name": nickname,
        },
    )
    session.flush()
    return {"user": _auth_user(user), "metadata": {"auth_provider": user.auth_provider}}


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise HTTPException(status_code=422, detail="invalid email")
    return normalized


def _normalize_display_name(display_name: str) -> str:
    nickname = re.sub(r"\s+", " ", display_name).strip()
    if not nickname:
        raise HTTPException(status_code=422, detail="display_name_required")
    if len(nickname) > 32:
        raise HTTPException(status_code=422, detail="display_name_too_long")
    return nickname


def _get_or_create_email_user(
    session: Session,
    *,
    email: str,
    platform: str | None,
    app_version: str | None,
) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is not None:
        user.platform = platform or user.platform
        user.app_version = app_version or user.app_version
        return user
    user = User(
        device_uid=new_email_device_uid(),
        email=email,
        display_name=email.split("@", 1)[0] or "路过的人",
        auth_provider="email",
        status="active",
        platform=platform,
        app_version=app_version,
        profile_json={},
    )
    session.add(user)
    session.flush()
    return user


def _active_session_by_refresh_token(session: Session, refresh_token: str) -> AuthSession:
    row = session.scalar(
        select(AuthSession)
        .where(
            AuthSession.refresh_token_hash == hash_refresh_token(refresh_token),
            AuthSession.status == "active",
        )
        .limit(1)
    )
    if row is None or row.expires_at < utcnow():
        raise HTTPException(status_code=401, detail="invalid refresh token")
    return row


def _enforce_code_rate_limits(
    session: Session,
    *,
    email: str,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    now = utcnow()
    cooldown_count = session.scalar(
        select(func.count())
        .select_from(EmailLoginCode)
        .where(EmailLoginCode.email == email, EmailLoginCode.sent_at >= now - timedelta(seconds=_COOLDOWN_SECONDS))
    )
    if int(cooldown_count or 0) > 0:
        _audit(session, action="rate_limited", email=email, ip_address=ip_address, user_agent=user_agent, metadata={"scope": "cooldown"})
        raise HTTPException(status_code=429, detail="code_request_too_frequent")

    hourly_email_count = session.scalar(
        select(func.count())
        .select_from(EmailLoginCode)
        .where(EmailLoginCode.email == email, EmailLoginCode.sent_at >= now - timedelta(hours=1))
    )
    if int(hourly_email_count or 0) >= _EMAIL_HOURLY_LIMIT:
        _audit(session, action="rate_limited", email=email, ip_address=ip_address, user_agent=user_agent, metadata={"scope": "email_hour"})
        raise HTTPException(status_code=429, detail="code_request_too_frequent")

    if ip_address:
        hourly_ip_count = session.scalar(
            select(func.count())
            .select_from(EmailLoginCode)
            .where(EmailLoginCode.request_ip == ip_address, EmailLoginCode.sent_at >= now - timedelta(hours=1))
        )
        if int(hourly_ip_count or 0) >= _IP_HOURLY_LIMIT:
            _audit(session, action="rate_limited", email=email, ip_address=ip_address, user_agent=user_agent, metadata={"scope": "ip_hour"})
            raise HTTPException(status_code=429, detail="code_request_too_frequent")


def _audit(
    session: Session,
    *,
    action: str,
    email: str | None = None,
    user: User | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuthAuditLog(
            user_id=user.id if user else None,
            email=email,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_json=metadata or {},
        )
    )


def _auth_user(user: User) -> dict[str, Any]:
    return AuthUser(id=str(user.id), email=user.email, display_name=user.display_name).model_dump()


def _token_pair(access_token: str, refresh_token: str, expires_in: int) -> dict[str, Any]:
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    ).model_dump()
