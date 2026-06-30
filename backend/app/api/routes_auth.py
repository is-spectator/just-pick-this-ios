from __future__ import annotations

from fastapi import APIRouter, Header, Request

from app.schemas.auth import (
    DeleteMeResponse,
    LogoutRequest,
    LogoutResponse,
    MeResponse,
    RefreshRequest,
    RefreshResponse,
    RequestCodeRequest,
    RequestCodeResponse,
    UpdateMeRequest,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.services import auth_service
from app.services.runtime import session_scope


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-code", response_model=RequestCodeResponse)
def request_code(payload: RequestCodeRequest, request: Request) -> dict:
    with session_scope() as session:
        return auth_service.request_login_code(
            session,
            email=payload.email,
            device_uid=payload.device_uid,
            platform=payload.platform,
            app_version=payload.app_version,
            ip_address=_client_host(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.post("/verify-code", response_model=VerifyCodeResponse)
def verify_code(payload: VerifyCodeRequest, request: Request) -> dict:
    with session_scope() as session:
        return auth_service.verify_login_code(
            session,
            email=payload.email,
            code=payload.code,
            device_uid=payload.device_uid,
            platform=payload.platform,
            app_version=payload.app_version,
            ip_address=_client_host(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(payload: RefreshRequest, request: Request) -> dict:
    with session_scope() as session:
        return auth_service.refresh_tokens(
            session,
            refresh_token=payload.refresh_token,
            ip_address=_client_host(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.post("/logout", response_model=LogoutResponse)
def logout(payload: LogoutRequest, request: Request) -> dict:
    with session_scope() as session:
        return auth_service.logout(
            session,
            refresh_token=payload.refresh_token,
            ip_address=_client_host(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.get("/me", response_model=MeResponse)
def me(authorization: str | None = Header(default=None)) -> dict:
    with session_scope() as session:
        return auth_service.me_from_authorization(session, authorization)


@router.patch("/me", response_model=MeResponse)
def update_me(
    payload: UpdateMeRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    with session_scope() as session:
        return auth_service.update_me_from_authorization(
            session,
            authorization,
            display_name=payload.display_name,
            ip_address=_client_host(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.delete("/me", response_model=DeleteMeResponse)
def delete_me(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    with session_scope() as session:
        return auth_service.delete_me_from_authorization(
            session,
            authorization,
            ip_address=_client_host(request),
            user_agent=request.headers.get("user-agent"),
        )


def _client_host(request: Request) -> str | None:
    return request.client.host if request.client else None
