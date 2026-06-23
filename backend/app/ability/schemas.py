from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field


AbilityToolName = Literal[
    "search_knowledge",
    "create_recommendation_card",
    "draft_help_card",
    "update_help_card",
    "publish_help_card",
    "submit_one_liner_answer",
    "finalize_help_card",
    "save_intent_answer",
    "light_user",
]

ToolResultStatus = Literal["succeeded", "failed", "denied", "skipped"]


class AbilityError(Exception):
    code = "ability_error"


class AbilityPermissionError(AbilityError):
    code = "tool_not_allowed"


class AbilityPreconditionError(AbilityError):
    code = "precondition_failed"


class AbilityPostconditionError(AbilityError):
    code = "postcondition_failed"


class AbilityToolNotFoundError(AbilityError):
    code = "tool_not_registered"


class AbilitySchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )


class ToolResult(AbilitySchema):
    tool_name: str
    status: ToolResultStatus = "succeeded"
    ok: bool
    output: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("output", "data"),
    )
    error: str | None = Field(
        default=None,
        validation_alias=AliasChoices("error", "error_message"),
    )
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def data(self) -> dict[str, Any]:
        return self.output or {}

    @computed_field
    @property
    def error_message(self) -> str | None:
        return self.error

    @classmethod
    def succeeded(
        cls,
        tool_name: str,
        output: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            tool_name=tool_name,
            status="succeeded",
            ok=True,
            output=_to_jsonable_dict(output),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failed(
        cls,
        tool_name: str,
        *,
        error: str,
        error_code: str,
        metadata: Mapping[str, Any] | None = None,
        status: ToolResultStatus = "failed",
    ) -> ToolResult:
        return cls(
            tool_name=tool_name,
            status=status,
            ok=False,
            error=error,
            error_code=error_code,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def denied(
        cls,
        tool_name: str,
        *,
        error: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        return cls.failed(
            tool_name,
            error=error,
            error_code=AbilityPermissionError.code,
            metadata=metadata,
            status="denied",
        )


class AbilityContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any | None = None
    agent_run_id: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_tools_specified: bool = False
    tool_call_logger: Any | None = None
    retrieval_logger: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        *,
        db: Any | None = None,
        agent_run_id: str | None = None,
        allowed_tools: Iterable[str] | None = None,
        tool_call_logger: Any | None = None,
        retrieval_logger: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> None:
        state_data = dict(state or {})
        metadata_data = {**state_data, **dict(metadata or {})}
        super().__init__(
            db=db,
            agent_run_id=agent_run_id,
            allowed_tools=list(allowed_tools or []),
            allowed_tools_specified=allowed_tools is not None,
            tool_call_logger=tool_call_logger,
            retrieval_logger=retrieval_logger,
            metadata=metadata_data,
            state=state_data,
        )

    def with_allowed_tools(self, allowed_tools: Iterable[str] | None) -> AbilityContext:
        return self.model_copy(
            update={
                "allowed_tools": list(allowed_tools or []),
                "allowed_tools_specified": True,
            }
        )


class ToolHandler(Protocol):
    def __call__(
        self,
        context: AbilityContext,
        input_data: BaseModel,
    ) -> Any | Awaitable[Any]: ...


InputAdapter = Callable[[Mapping[str, Any], AbilityContext], Mapping[str, Any]]
PreconditionHook = Callable[[AbilityContext, BaseModel], Any | Awaitable[Any]]
PostconditionHook = Callable[[AbilityContext, BaseModel, Any], Any | Awaitable[Any]]


class AbilityTool:
    name: str = ""
    input_model: type[BaseModel] | None = None

    def __init__(
        self,
        name: str | None = None,
        input_schema: type[BaseModel] | None = None,
        handler: ToolHandler | None = None,
        *,
        output_schema: type[BaseModel] | None = None,
        description: str | None = None,
        input_adapter: InputAdapter | None = None,
        preconditions: Iterable[PreconditionHook] = (),
        postconditions: Iterable[PostconditionHook] = (),
        input_model: type[BaseModel] | None = None,
    ) -> None:
        resolved_input = (
            input_schema
            or input_model
            or getattr(self, "input_schema", None)
            or getattr(self, "input_model", None)
        )
        self.name = name or getattr(self, "name", "")
        self.input_schema = resolved_input
        self.input_model = resolved_input
        self.handler = handler
        self.output_schema = output_schema
        self.description = description
        self.input_adapter = input_adapter
        self.preconditions = tuple(preconditions)
        self.postconditions = tuple(postconditions)

    def with_preconditions(self, *hooks: PreconditionHook) -> AbilityTool:
        return self._copy(preconditions=(*self.preconditions, *hooks))

    def with_postconditions(self, *hooks: PostconditionHook) -> AbilityTool:
        return self._copy(postconditions=(*self.postconditions, *hooks))

    def precondition(
        self,
        args: BaseModel | dict[str, Any],
        context: AbilityContext,
    ) -> ToolResult | None:
        return None

    def postcondition(self, result: ToolResult, context: AbilityContext) -> ToolResult:
        return result

    def execute(
        self,
        args: BaseModel | dict[str, Any],
        context: AbilityContext,
    ) -> ToolResult:
        return ToolResult.failed(
            self.name,
            error="tool_not_implemented",
            error_code="tool_not_implemented",
        )

    def _copy(self, **updates: Any) -> AbilityTool:
        values = {
            "name": self.name,
            "input_schema": self.input_schema,
            "handler": self.handler,
            "output_schema": self.output_schema,
            "description": self.description,
            "input_adapter": self.input_adapter,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
        }
        values.update(updates)
        return AbilityTool(**values)


class FinalizeHelpCardInput(AbilitySchema):
    help_card_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("help_card_id", "help_request_id"),
    )
    question_id: str | None = Field(default=None, min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    evidence_answer_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str = Field(default="pipi_finalize_graph", min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalizeHelpCardOutput(AbilitySchema):
    help_card_id: str
    question_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    status: Literal["finalize_accepted", "needs_more_answers"] = "finalize_accepted"
    evidence_answer_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    source: str = "pipi_finalize_graph"


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _to_jsonable_dict(value: Any) -> dict[str, Any]:
    converted = to_jsonable(value)
    if converted is None:
        return {}
    if isinstance(converted, dict):
        return converted
    return {"value": converted}


__all__ = [
    "AbilityContext",
    "AbilityError",
    "AbilityPermissionError",
    "AbilityPostconditionError",
    "AbilityPreconditionError",
    "AbilitySchema",
    "AbilityTool",
    "AbilityToolName",
    "AbilityToolNotFoundError",
    "FinalizeHelpCardInput",
    "FinalizeHelpCardOutput",
    "InputAdapter",
    "PostconditionHook",
    "PreconditionHook",
    "ToolHandler",
    "ToolResult",
    "ToolResultStatus",
    "to_jsonable",
]
