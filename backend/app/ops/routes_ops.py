from __future__ import annotations

import uuid
from pathlib import Path
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.admin.routes import _request_json, _serialize_trace_summary, _write_audit
from app.config import get_settings
from app.db import get_db_session
from app.debug.routes import _serialize_agent_run, _serialize_turn
from app.models import AgentRun, Conversation, Turn
from app.ops.graph_manifest import graph_manifest
from app.ops.prompt_registry import PromptRegistry
from app.ops.prompt_service import (
    DEFAULT_ENVIRONMENT,
    create_draft,
    dry_run_prompt,
    get_prompt_detail,
    list_prompts,
    publish_prompt,
    rollback_prompt,
    serialize_prompt_version,
)


_STATIC_DIR = Path(__file__).resolve().parents[1] / "ops_static"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _settings(request: Request) -> Any:
    settings = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def _require_ops_admin(request: Request) -> str:
    configured = _settings(request).admin_token
    if configured is None:
        raise HTTPException(status_code=401, detail="admin token required")
    expected = configured.get_secret_value()
    authorization = request.headers.get("authorization") or ""
    bearer = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not bearer or not compare_digest(bearer, expected):
        raise HTTPException(status_code=401, detail="admin token required")
    actor = request.headers.get("x-admin-actor") or "ops-token"
    request.state.admin_actor = actor
    return actor


def _actor(request: Request) -> str:
    actor = getattr(request.state, "admin_actor", None)
    if isinstance(actor, str) and actor:
        return actor
    return _require_ops_admin(request)


router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(_require_ops_admin)])


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def ops_root() -> HTMLResponse:
    return HTMLResponse(_INDEX_HTML.read_text(encoding="utf-8"))


@router.get("/static/{asset_path:path}", include_in_schema=False)
def ops_static(asset_path: str) -> FileResponse:
    path = (_STATIC_DIR / asset_path).resolve()
    if not str(path).startswith(str(_STATIC_DIR.resolve())) or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path)


@router.get("/api/agent/graph")
def get_ops_agent_graph(
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    prompt_versions = PromptRegistry(session, environment=environment).load_active_pack()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_agent_graph",
        target_record_id=None,
        request_json=_request_json(request, {"environment": environment}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return graph_manifest(prompt_versions)


@router.get("/api/traces")
def list_ops_traces(
    request: Request,
    query: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    stmt = select(AgentRun)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                cast(AgentRun.id, String).ilike(pattern),
                cast(AgentRun.conversation_id, String).ilike(pattern),
                cast(AgentRun.turn_id, String).ilike(pattern),
                AgentRun.run_type.ilike(pattern),
                AgentRun.graph_name.ilike(pattern),
                AgentRun.status.ilike(pattern),
                AgentRun.error_message.ilike(pattern),
            )
        )
    rows = session.scalars(stmt.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)).all()
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="ops_traces",
        target_record_id=None,
        request_json=_request_json(request, {"query": query, "limit": limit, "offset": offset}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": [_serialize_trace_summary(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/api/traces/{agent_run_id}")
def get_ops_trace(
    agent_run_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    run = _agent_run(session, agent_run_id)
    conversation = session.get(Conversation, run.conversation_id)
    turn = session.get(Turn, run.turn_id) if run.turn_id else None
    serialized = _serialize_agent_run(session, run)
    output_json = serialized.get("output_json") if isinstance(serialized.get("output_json"), dict) else {}
    input_json = serialized.get("input_json") if isinstance(serialized.get("input_json"), dict) else {}
    retrieval_runs = serialized.get("retrieval_runs") or []
    retrieval_hits = [hit for item in retrieval_runs for hit in item.get("hits", [])]
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_traces",
        target_record_id=agent_run_id,
        request_json=_request_json(request),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {
        "agent_run": serialized,
        "conversation": {"id": str(conversation.id), "title": conversation.title} if conversation else None,
        "turn": _serialize_turn(turn) if turn else None,
        "loop_trace": output_json.get("loop_trace") or [],
        "tool_calls": serialized.get("tool_calls") or [],
        "retrieval_runs": retrieval_runs,
        "retrieval_hits": retrieval_hits,
        "ui_events": output_json.get("ui_events") or output_json.get("events") or [],
        "prompt_versions": input_json.get("prompt_versions") or {},
    }


@router.get("/api/prompts")
def list_ops_prompts(
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    items = list_prompts(session, environment=environment)
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="list",
        table_name="ops_prompts",
        target_record_id=None,
        request_json=_request_json(request, {"environment": environment, "total": len(items)}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return {"items": items}


@router.get("/api/prompts/{prompt_key}")
def get_ops_prompt(
    prompt_key: str,
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        item = get_prompt_detail(session, prompt_key, environment=environment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="read",
        table_name="ops_prompts",
        target_record_id=prompt_key,
        request_json=_request_json(request, {"environment": environment}),
        before_json=None,
        after_json=None,
    )
    session.commit()
    return item


@router.post("/api/prompts/{prompt_key}/draft")
def create_ops_prompt_draft(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        version = create_draft(session, prompt_key, payload, actor=actor, environment=environment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="draft",
        table_name="ops_prompts",
        target_record_id=prompt_key,
        request_json=_request_json(request, payload),
        before_json=None,
        after_json=serialize_prompt_version(version),
    )
    session.commit()
    return {"item": serialize_prompt_version(version)}


@router.post("/api/prompts/{prompt_key}/dry-run")
def dry_run_ops_prompt(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        result = dry_run_prompt(session, prompt_key, payload, actor=actor, environment=environment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="dry_run",
        table_name="ops_prompts",
        target_record_id=prompt_key,
        request_json=_request_json(request, payload),
        before_json=None,
        after_json=result,
    )
    session.commit()
    return result


@router.post("/api/prompts/{prompt_key}/publish")
def publish_ops_prompt(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        version = publish_prompt(session, prompt_key, payload, actor=actor, environment=environment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="publish",
        table_name="ops_prompts",
        target_record_id=prompt_key,
        request_json=_request_json(request, payload),
        before_json=None,
        after_json=serialize_prompt_version(version),
    )
    session.commit()
    PromptRegistry.invalidate(environment)
    return {"item": serialize_prompt_version(version), "hot_reload": "next_chat_turn"}


@router.post("/api/prompts/{prompt_key}/rollback")
def rollback_ops_prompt(
    prompt_key: str,
    payload: dict[str, Any],
    request: Request,
    environment: str = Query(default=DEFAULT_ENVIRONMENT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        version = rollback_prompt(session, prompt_key, payload, actor=actor, environment=environment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _write_audit(
        session,
        request=request,
        actor=actor,
        action="rollback",
        table_name="ops_prompts",
        target_record_id=prompt_key,
        request_json=_request_json(request, payload),
        before_json=None,
        after_json=serialize_prompt_version(version),
    )
    session.commit()
    PromptRegistry.invalidate(environment)
    return {"item": serialize_prompt_version(version), "hot_reload": "next_chat_turn"}


@router.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
def ops_spa(path: str) -> HTMLResponse:
    del path
    return HTMLResponse(_INDEX_HTML.read_text(encoding="utf-8"))


def _agent_run(session: Session, agent_run_id: str) -> AgentRun:
    try:
        run_id = uuid.UUID(agent_run_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="trace not found") from exc
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return run
