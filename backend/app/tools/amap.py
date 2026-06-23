from __future__ import annotations

import anyio

from app.schemas.tools import (
    AmapGeocodeInput,
    AmapGeocodeOutput,
    AmapPoiSearchInput,
    AmapPoiSearchOutput,
    AmapReverseGeocodeInput,
    AmapReverseGeocodeOutput,
    AmapRoutePlanInput,
    AmapRoutePlanOutput,
    BuildAmapUriInput,
    BuildAmapUriOutput,
)
from app.services.amap_service import AmapService
from app.tools.session import SessionLike
from app.tools.tool_call_logger import (
    ToolCallLogger,
    ensure_tool_call_logger,
    finish_tool_call,
    start_tool_call,
)


async def amap_geocode(
    db: SessionLike,
    input_data: AmapGeocodeInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> AmapGeocodeOutput:
    return await _run_amap_tool(db, "amap_geocode", input_data, agent_run_id, tool_call_logger)


async def amap_reverse_geocode(
    db: SessionLike,
    input_data: AmapReverseGeocodeInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> AmapReverseGeocodeOutput:
    return await _run_amap_tool(db, "amap_reverse_geocode", input_data, agent_run_id, tool_call_logger)


async def amap_poi_search(
    db: SessionLike,
    input_data: AmapPoiSearchInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> AmapPoiSearchOutput:
    return await _run_amap_tool(db, "amap_poi_search", input_data, agent_run_id, tool_call_logger)


async def amap_route_plan(
    db: SessionLike,
    input_data: AmapRoutePlanInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> AmapRoutePlanOutput:
    return await _run_amap_tool(db, "amap_route_plan", input_data, agent_run_id, tool_call_logger)


async def build_amap_uri(
    db: SessionLike,
    input_data: BuildAmapUriInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> BuildAmapUriOutput:
    return await _run_amap_tool(db, "build_amap_uri", input_data, agent_run_id, tool_call_logger)


async def _run_amap_tool(
    db: SessionLike,
    tool_name: str,
    input_data: object,
    agent_run_id: str | None,
    tool_call_logger: ToolCallLogger | None,
):
    tool_call_logger = ensure_tool_call_logger(db, tool_call_logger, agent_run_id=agent_run_id)
    payload = input_data.model_dump(mode="json")  # type: ignore[attr-defined]
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name=tool_name,
        input_json=payload,
        agent_run_id=agent_run_id,
    )
    try:
        service = AmapService()
        if tool_name == "amap_geocode":
            output = await anyio.to_thread.run_sync(lambda: service.geocode(input_data))  # type: ignore[arg-type]
        elif tool_name == "amap_reverse_geocode":
            output = await anyio.to_thread.run_sync(lambda: service.reverse_geocode(input_data))  # type: ignore[arg-type]
        elif tool_name == "amap_poi_search":
            output = await anyio.to_thread.run_sync(lambda: service.poi_search(input_data))  # type: ignore[arg-type]
        elif tool_name == "amap_route_plan":
            output = await anyio.to_thread.run_sync(lambda: service.route_plan(input_data))  # type: ignore[arg-type]
        else:
            output = service.build_uri(input_data)  # type: ignore[arg-type]
        await finish_tool_call(
            tool_call_logger,
            tool_call_id=tool_call_id,
            status="succeeded",
            output_json=output.model_dump(mode="json"),
        )
        return output
    except Exception as error:
        await finish_tool_call(tool_call_logger, tool_call_id=tool_call_id, status="failed", error_message=str(error))
        raise
