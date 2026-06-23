from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ability.schemas import (
    AbilityContext,
    AbilityError,
    AbilityPermissionError,
    AbilityPostconditionError,
    AbilityTool,
    AbilityToolNotFoundError,
    PostconditionHook,
    PreconditionHook,
    ToolResult,
    to_jsonable,
)


class AbilityCenter:
    """Schema-checked, permission-aware boundary for Pipi tool calls."""

    def __init__(
        self,
        tools: Iterable[AbilityTool] | Mapping[str, AbilityTool] | None = None,
        *,
        allowed_tools: Iterable[str] | None = None,
    ) -> None:
        self._tools: dict[str, AbilityTool] = {}
        self.registry = self._tools
        self._allowed_tools = list(allowed_tools) if allowed_tools is not None else None
        if tools is not None:
            if isinstance(tools, Mapping):
                tools = tools.values()
            for tool in tools:
                self.register(tool)

    def register(self, tool: AbilityTool) -> AbilityCenter:
        self._tools[tool.name] = tool
        return self

    def add_precondition(self, tool_name: str, hook: PreconditionHook) -> AbilityCenter:
        tool = self.get_tool(tool_name)
        self._tools[tool_name] = tool.with_preconditions(hook)
        return self

    def add_postcondition(self, tool_name: str, hook: PostconditionHook) -> AbilityCenter:
        tool = self.get_tool(tool_name)
        self._tools[tool_name] = tool.with_postconditions(hook)
        return self

    def get_tool(self, tool_name: str) -> AbilityTool:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise AbilityToolNotFoundError(f"Tool is not registered: {tool_name}")
        return tool

    def list_tools(self) -> list[str]:
        return sorted(self._tools)

    def tool_schemas(self) -> dict[str, dict[str, Any]]:
        schemas: dict[str, dict[str, Any]] = {}
        for name, tool in sorted(self._tools.items()):
            if tool.input_schema is not None:
                schemas[name] = tool.input_schema.model_json_schema()
            else:
                schemas[name] = {"type": "object"}
        return schemas

    async def call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        state: Any,
    ) -> ToolResult:
        return await self.execute(
            tool_name,
            tool_args,
            context=_context_from_state(state),
        )

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | BaseModel | None = None,
        *,
        context: AbilityContext | None = None,
        allowed_tools: Iterable[str] | None = None,
    ) -> ToolResult:
        context = context or AbilityContext()
        if allowed_tools is not None:
            context = context.with_allowed_tools(allowed_tools)
        raw_arguments = _payload_from_arguments(arguments)

        try:
            tool = self.get_tool(tool_name)
        except AbilityToolNotFoundError as error:
            return ToolResult.failed(
                tool_name,
                error=str(error),
                error_code=error.code,
            )

        if not self._is_allowed(tool_name, context):
            result = ToolResult.denied(
                tool_name,
                error="tool_not_allowed",
                metadata={"requested_tool": tool_name},
            )
            return await self._persist_terminal_result(
                context,
                tool_name,
                raw_arguments,
                result,
            )

        try:
            input_data = self.validate_input(tool, arguments, context)
        except ValidationError as error:
            result = ToolResult.failed(
                tool_name,
                error=str(error),
                error_code="schema_validation_error",
                metadata={"errors": error.errors(include_url=False)},
            )
            return await self._persist_terminal_result(
                context,
                tool_name,
                raw_arguments,
                result,
            )
        except AbilityError as error:
            result = ToolResult.failed(
                tool_name,
                error=str(error),
                error_code=error.code,
            )
            return await self._persist_terminal_result(
                context,
                tool_name,
                raw_arguments,
                result,
            )
        except Exception as error:
            result = ToolResult.failed(
                tool_name,
                error=str(error),
                error_code=str(getattr(error, "code", "schema_validation_error")),
            )
            return await self._persist_terminal_result(
                context,
                tool_name,
                raw_arguments,
                result,
            )

        context, logger, tool_call_id, start_error = await self._start_tool_call(
            context,
            tool_name,
            _jsonable_dict(input_data),
        )
        if start_error is not None:
            return start_error

        try:
            for hook in tool.preconditions:
                await _maybe_await(hook(context, input_data))

            legacy_precondition = tool.precondition(input_data, context)
            if legacy_precondition is not None:
                return await self._finish_tool_call(logger, tool_call_id, legacy_precondition)

            if tool.handler is not None:
                raw_output = await _maybe_await(tool.handler(context, input_data))
            else:
                raw_output = await _maybe_await(tool.execute(input_data, context))

            if isinstance(raw_output, ToolResult):
                result = tool.postcondition(raw_output, context)
                return await self._finish_tool_call(logger, tool_call_id, result)

            output = self.validate_output(tool, raw_output)
            for hook in tool.postconditions:
                replacement = await _maybe_await(hook(context, input_data, output))
                if replacement is not None:
                    output = self.validate_output(tool, replacement)

            result = ToolResult.succeeded(tool_name, output)
            result = tool.postcondition(result, context)
            return await self._finish_tool_call(logger, tool_call_id, result)
        except ValidationError as error:
            result = ToolResult.failed(
                tool_name,
                error=str(error),
                error_code="schema_validation_error",
                metadata={"errors": error.errors(include_url=False)},
            )
            return await self._finish_tool_call(logger, tool_call_id, result)
        except AbilityError as error:
            result = ToolResult.failed(
                tool_name,
                error=str(error),
                error_code=error.code,
            )
            return await self._finish_tool_call(logger, tool_call_id, result)
        except Exception as error:
            result = ToolResult.failed(
                tool_name,
                error=str(error),
                error_code=str(getattr(error, "code", "tool_execution_error")),
            )
            return await self._finish_tool_call(logger, tool_call_id, result)

    invoke = execute
    run_tool = execute

    async def execute_or_raise(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | BaseModel | None = None,
        *,
        context: AbilityContext | None = None,
        allowed_tools: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        result = await self.execute(
            tool_name,
            arguments,
            context=context,
            allowed_tools=allowed_tools,
        )
        if not result.ok:
            raise AbilityError(result.error or f"Tool failed: {tool_name}")
        return result.output or {}

    def validate_input(
        self,
        tool: AbilityTool,
        arguments: Mapping[str, Any] | BaseModel | None,
        context: AbilityContext | None = None,
    ) -> BaseModel | dict[str, Any]:
        context = context or AbilityContext()
        payload = _payload_from_arguments(arguments)
        if tool.input_adapter is not None:
            payload = dict(tool.input_adapter(payload, context))
        if tool.input_schema is None:
            return payload
        return tool.input_schema.model_validate(payload)

    def validate_output(self, tool: AbilityTool, output: Any) -> Any:
        if tool.output_schema is None:
            return output
        if isinstance(output, tool.output_schema):
            return output
        if isinstance(output, BaseModel):
            return tool.output_schema.model_validate(output.model_dump(mode="json"))
        return tool.output_schema.model_validate(output)

    def _is_allowed(self, tool_name: str, context: AbilityContext) -> bool:
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            return False
        if context.allowed_tools_specified and tool_name not in context.allowed_tools:
            return False
        return True

    async def _persist_terminal_result(
        self,
        context: AbilityContext,
        tool_name: str,
        input_json: Mapping[str, Any],
        result: ToolResult,
    ) -> ToolResult:
        context, logger, tool_call_id, start_error = await self._start_tool_call(
            context,
            tool_name,
            _jsonable_dict(input_json),
        )
        if start_error is not None:
            return start_error
        return await self._finish_tool_call(logger, tool_call_id, result)

    async def _start_tool_call(
        self,
        context: AbilityContext,
        tool_name: str,
        input_json: Mapping[str, Any],
    ) -> tuple[AbilityContext, Any | None, str | None, ToolResult | None]:
        logger = _resolve_tool_call_logger(context)
        if logger is None:
            return context, None, None, None

        payload = _jsonable_dict(input_json)
        try:
            record = await _maybe_await(
                logger.start_tool_call(
                    tool_name=tool_name,
                    input_json=payload,
                    agent_run_id=context.agent_run_id,
                    question_id=_question_id_from(payload, context),
                    help_request_id=_help_card_id_from(payload, context),
                )
            )
        except Exception as error:
            return (
                context,
                None,
                None,
                ToolResult.failed(
                    tool_name,
                    error=str(error),
                    error_code="tool_call_persistence_failed",
                ),
            )

        tool_call_id = str(getattr(record, "id", "")) if record is not None else None
        if not tool_call_id:
            return context, logger, None, None

        metadata = {**context.metadata, "tool_call_id": tool_call_id}
        wrapped_logger = _PrestartedToolCallLogger(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            input_json=payload,
            agent_run_id=context.agent_run_id,
        )
        return (
            context.model_copy(
                update={
                    "tool_call_logger": wrapped_logger,
                    "metadata": metadata,
                }
            ),
            logger,
            tool_call_id,
            None,
        )

    async def _finish_tool_call(
        self,
        logger: Any | None,
        tool_call_id: str | None,
        result: ToolResult,
    ) -> ToolResult:
        result = _attach_tool_call_id(result, tool_call_id)
        if logger is None:
            return result

        status = "succeeded" if result.ok and result.status == "succeeded" else "failed"
        output_json = result.output if result.ok else None
        try:
            await _maybe_await(
                logger.finish_tool_call(
                    tool_call_id=tool_call_id,
                    status=status,
                    output_json=output_json,
                    error_message=result.error,
                )
            )
        except Exception as error:
            return ToolResult.failed(
                result.tool_name,
                error=str(error),
                error_code="tool_call_persistence_failed",
                metadata=result.metadata,
            )
        return result


def _context_from_state(state: Any) -> AbilityContext:
    if isinstance(state, AbilityContext):
        return state
    if hasattr(state, "model_dump"):
        data = state.model_dump()
    elif isinstance(state, dict):
        data = dict(state)
    else:
        data = dict(getattr(state, "__dict__", {}) or {})
    metadata = dict(data.get("metadata") or {})
    context_pack = data.get("context_pack")
    if isinstance(context_pack, dict):
        strongest_evidence = context_pack.get("strongest_evidence")
        retrieval_hits = context_pack.get("retrieval_hits") or strongest_evidence
        if retrieval_hits is not None:
            metadata.setdefault("retrieval_hits", retrieval_hits)
        if strongest_evidence is not None:
            metadata.setdefault("strongest_evidence", strongest_evidence)
    return AbilityContext(
        db=data.get("db") or metadata.get("db"),
        agent_run_id=data.get("agent_run_id") or metadata.get("agent_run_id"),
        allowed_tools=data.get("allowed_tools") if "allowed_tools" in data else None,
        tool_call_logger=data.get("tool_call_logger") or metadata.get("tool_call_logger"),
        retrieval_logger=data.get("retrieval_logger") or metadata.get("retrieval_logger"),
        metadata=metadata,
        state=data,
    )


def _payload_from_arguments(arguments: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, BaseModel):
        return arguments.model_dump(mode="json")
    return dict(arguments)


def _resolve_tool_call_logger(context: AbilityContext) -> Any | None:
    if context.tool_call_logger is not None:
        return context.tool_call_logger
    if context.db is None or context.agent_run_id is None:
        return None

    from app.tools.tool_call_logger import ensure_tool_call_logger

    return ensure_tool_call_logger(
        context.db,
        None,
        agent_run_id=context.agent_run_id,
        turn_id=_turn_id_from(context),
        sequence_index=_sequence_index_from(context),
    )


def _jsonable_dict(value: Any) -> dict[str, Any]:
    converted = to_jsonable(value)
    if converted is None:
        return {}
    if isinstance(converted, dict):
        return converted
    return {"value": converted}


def _question_id_from(input_json: Mapping[str, Any], context: AbilityContext) -> str | None:
    value = input_json.get("question_id") or context.metadata.get("question_id")
    return str(value) if value else None


def _help_card_id_from(input_json: Mapping[str, Any], context: AbilityContext) -> str | None:
    value = (
        input_json.get("help_card_id")
        or input_json.get("help_request_id")
        or context.metadata.get("help_card_id")
        or context.metadata.get("active_help_card_id")
    )
    return str(value) if value else None


def _turn_id_from(context: AbilityContext) -> str | None:
    value = (
        context.metadata.get("turn_id")
        or context.metadata.get("user_turn_id")
        or context.state.get("turn_id")
        or context.state.get("user_turn_id")
    )
    return str(value) if value else None


def _sequence_index_from(context: AbilityContext) -> int:
    value = context.metadata.get("tool_call_sequence_index") or context.metadata.get("sequence_index")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _attach_tool_call_id(result: ToolResult, tool_call_id: str | None) -> ToolResult:
    if not tool_call_id:
        return result
    return result.model_copy(update={"metadata": {**result.metadata, "tool_call_id": tool_call_id}})


class _PrestartedToolCallLogger:
    """Let legacy DB tools reuse the AbilityCenter-created tool_call row."""

    def __init__(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        input_json: dict[str, Any],
        agent_run_id: str | None,
    ) -> None:
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.input_json = input_json
        self.agent_run_id = agent_run_id

    async def start_tool_call(
        self,
        *,
        tool_name: str,
        input_json: dict[str, Any],
        agent_run_id: str | None = None,
        question_id: str | None = None,
        help_request_id: str | None = None,
    ) -> Any:
        del tool_name, input_json, question_id, help_request_id
        return SimpleNamespace(
            id=self.tool_call_id,
            tool_name=self.tool_name,
            input_json=self.input_json,
            status="running",
            agent_run_id=agent_run_id or self.agent_run_id,
        )

    async def finish_tool_call(
        self,
        *,
        tool_call_id: str | None,
        status: str,
        output_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        del tool_call_id, status, output_json, error_message


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "AbilityCenter",
    "AbilityContext",
    "AbilityError",
    "AbilityPermissionError",
    "AbilityPostconditionError",
    "AbilityTool",
    "ToolResult",
]
