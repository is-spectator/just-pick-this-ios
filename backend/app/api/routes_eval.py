"""Eval-only routes used by pipi-eval-lab."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.eval import (
    EvalResetRequest,
    EvalResetResponse,
    EvalSeedFoodRequest,
    EvalSeedFoodResponse,
    EvalSeedNegativeResponse,
    EvalSeedStatusResponse,
    EvalTraceConversationResponse,
    EvalTraceTurnResponse,
)


router = APIRouter(tags=["eval"])


@router.post("/eval/reset", response_model=EvalResetResponse)
async def eval_reset(payload: EvalResetRequest) -> EvalResetResponse:
    handler = resolve_service_handler("app.services.eval_runtime", "reset_eval")
    return await call_service(handler, dump_model(payload))


@router.post("/eval/seed/food-beijing-onsite-v1", response_model=EvalSeedFoodResponse)
async def eval_seed_food(payload: EvalSeedFoodRequest) -> EvalSeedFoodResponse:
    handler = resolve_service_handler("app.services.eval_runtime", "seed_food_beijing_onsite_v1")
    return await call_service(handler, dump_model(payload))


@router.post("/eval/seed/negative-cases", response_model=EvalSeedNegativeResponse)
async def eval_seed_negative_cases() -> EvalSeedNegativeResponse:
    handler = resolve_service_handler("app.services.eval_runtime", "seed_negative_cases")
    return await call_service(handler)


@router.get("/eval/seed/status", response_model=EvalSeedStatusResponse)
async def eval_seed_status() -> EvalSeedStatusResponse:
    handler = resolve_service_handler("app.services.eval_runtime", "seed_status")
    return await call_service(handler)


@router.get(
    "/eval/traces/conversations/{conversation_id}",
    response_model=EvalTraceConversationResponse,
)
async def eval_trace_conversation(conversation_id: str) -> EvalTraceConversationResponse:
    handler = resolve_service_handler("app.services.eval_runtime", "trace_by_conversation")
    return await call_service(handler, conversation_id)


@router.get("/eval/traces/turns/{turn_id}", response_model=EvalTraceTurnResponse)
async def eval_trace_turn(turn_id: str) -> EvalTraceTurnResponse:
    handler = resolve_service_handler("app.services.eval_runtime", "trace_by_turn")
    return await call_service(handler, turn_id)
