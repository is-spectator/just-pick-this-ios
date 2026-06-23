from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified


OUTPUT_FIELDS = ("output_json", "output_snapshot")
_MISSING = object()
HARNESS_TRACE_EVENT_NAMES = (
    "input_gate_result",
    "context_pack",
    "reasoner_decision",
    "reasoner_provider_fallback",
    "tool_call",
    "tool_result",
    "evaluator_result",
    "answer_gate_result",
)
SHADOW_TRACE_EVENT_NAMES = ("shadow_reasoner_result",)
TRACE_EVENT_NAMES = (*HARNESS_TRACE_EVENT_NAMES, *SHADOW_TRACE_EVENT_NAMES)


class TraceStore:
    """Append harness events to an AgentRun-compatible JSON trace field.

    The store can be used with an AgentRun object directly, with a SQLAlchemy
    session plus agent_run_id, or as an in-memory collector before a run exists.
    When a run is available, events are appended to ``loop_trace`` under the
    first compatible output field that preserves existing data.
    """

    def __init__(
        self,
        session: Any | None = None,
        agent_run: Any | None = None,
        *,
        auto_flush: bool = True,
    ) -> None:
        if agent_run is None and _looks_like_agent_run(session):
            agent_run = session
            session = None
        self.session = session
        self.agent_run = agent_run
        self.auto_flush = auto_flush
        self.events: list[dict[str, Any]] = []

    def record_input_gate(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._record_stage("input_gate_result", first, second, **fields)

    def record_context_pack(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._record_stage("context_pack", first, second, **fields)

    def record_reasoner_decision(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._record_stage("reasoner_decision", first, second, **fields)

    def record_shadow_reasoner_result(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._record_stage("shadow_reasoner_result", first, second, **fields)

    def record_tool_call(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        if second is _MISSING and not _looks_like_agent_run(first):
            return self._record_stage(
                "tool_call",
                _normalize_tool_call_payload(first),
                second,
                **fields,
            )
        return self._record_stage(
            "tool_call",
            first,
            _normalize_tool_call_payload(_none_if_missing(second))
            if second is not _MISSING
            else second,
            **fields,
        )

    def record_tool_result(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        third: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        if third is not _MISSING:
            tool_call = _normalize_tool_call_payload(second)
            if not self._last_event_matches("tool_call", tool_call):
                self.record_tool_call(first, tool_call)
            payload = {
                "decision": tool_call,
                "tool_call": tool_call,
                "tool_result": _json_safe(third),
            }
            return self._record_stage("tool_result", first, payload, **fields)
        return self._record_stage("tool_result", first, second, **fields)

    def record_evaluator_result(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._record_stage("evaluator_result", first, second, **fields)

    def record_answer_gate_result(
        self,
        first: Any | None = None,
        second: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._record_stage("answer_gate_result", first, second, **fields)

    def record_event(
        self,
        event_name: str,
        agent_run: Any | None = None,
        payload: Any = _MISSING,
        **fields: Any,
    ) -> dict[str, Any]:
        """Append a named event and return the stored event."""

        if payload is _MISSING and not _looks_like_agent_run(agent_run):
            payload = agent_run
            agent_run = None
        if isinstance(agent_run, (str, UUID)) and self.session is not None:
            fields.setdefault("agent_run_id", agent_run)
            agent_run = None
        if payload is _MISSING:
            payload = None

        agent_run_id = fields.pop("agent_run_id", None)
        if agent_run_id is None:
            agent_run_id = fields.pop("run_id", None)
        if agent_run_id is None and isinstance(payload, Mapping):
            payload = dict(payload)
            agent_run_id = payload.pop("agent_run_id", payload.pop("run_id", None))

        run = self._resolve_agent_run(agent_run=agent_run, agent_run_id=agent_run_id)
        trace = self._current_trace(run)
        stage = str(fields.pop("stage", event_name))
        event_payload = self._merge_payload(payload, fields)
        event = {
            "event": event_name,
            "name": event_name,
            "type": event_name,
            "stage": stage,
            "sequence_index": len(trace) if run is not None else len(self.events),
            "sequence": len(trace) if run is not None else len(self.events),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "payload": event_payload,
            "data": event_payload,
        }

        self.events.append(event)
        if run is None:
            return event

        output_field = self._select_output_field(run)
        output = self._copy_output(getattr(run, output_field, None))
        output["loop_trace"] = [*trace, event]
        setattr(run, output_field, output)
        self._mark_modified(run, output_field)
        self._flush()
        return event

    def _record_stage(
        self,
        event_name: str,
        first: Any | None,
        second: Any,
        **fields: Any,
    ) -> dict[str, Any]:
        if _looks_like_agent_run(first):
            return self.record_event(event_name, agent_run=first, payload=_none_if_missing(second), **fields)
        if isinstance(first, (str, UUID)) and self.session is not None and second is not _MISSING:
            return self.record_event(event_name, agent_run=first, payload=second, **fields)
        if second is not _MISSING:
            return self.record_event(event_name, payload=second, **fields)
        return self.record_event(event_name, payload=first, **fields)

    def _resolve_agent_run(self, *, agent_run: Any | None, agent_run_id: Any | None) -> Any | None:
        if agent_run is not None:
            return agent_run
        if self.agent_run is not None:
            return self.agent_run
        if agent_run_id is None:
            return None
        if self.session is None:
            raise ValueError("TraceStore requires a session to load by agent_run_id.")

        from app.models import AgentRun

        run = self.session.get(AgentRun, _coerce_uuid(agent_run_id))
        if run is None:
            raise ValueError(f"AgentRun not found: {agent_run_id}")
        return run

    def _current_trace(self, agent_run: Any | None) -> list[Any]:
        if agent_run is None:
            return list(self.events)
        output_field = self._select_output_field(agent_run)
        output = self._copy_output(getattr(agent_run, output_field, None))
        return self._copy_loop_trace(output.get("loop_trace"))

    @staticmethod
    def _select_output_field(agent_run: Any) -> str:
        available = [field for field in OUTPUT_FIELDS if hasattr(agent_run, field)]
        if not available:
            raise AttributeError("AgentRun has no output_json or output_snapshot field.")

        for field in available:
            value = getattr(agent_run, field, None)
            if isinstance(value, Mapping) and "loop_trace" in value:
                return field
        for field in available:
            if _has_existing_output(getattr(agent_run, field, None)):
                return field
        for field in available:
            if getattr(agent_run, field, None) is not None:
                return field
        return available[0]

    @staticmethod
    def _copy_output(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return copy.deepcopy(dict(value))
        return {"_legacy_output": _json_safe(value)}

    @staticmethod
    def _copy_loop_trace(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return copy.deepcopy(value)
        return [{"event": "legacy_loop_trace", "payload": _json_safe(value), "data": _json_safe(value)}]

    @staticmethod
    def _merge_payload(payload: Any | None, fields: Mapping[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if payload is not None:
            if isinstance(payload, Mapping):
                merged.update(dict(payload))
            else:
                merged["value"] = payload
        merged.update(fields)
        return _json_safe(merged)

    @staticmethod
    def _mark_modified(agent_run: Any, field_name: str) -> None:
        try:
            flag_modified(agent_run, field_name)
        except Exception:
            # Plain objects and detached test doubles do not need SQLAlchemy state tracking.
            return

    def _flush(self) -> None:
        if not self.auto_flush or self.session is None:
            return
        flush = getattr(self.session, "flush", None)
        if flush is not None:
            flush()

    def _last_event_matches(self, event_name: str, payload: Mapping[str, Any]) -> bool:
        if not self.events:
            return False
        last = self.events[-1]
        if last.get("event") != event_name:
            return False
        last_payload = last.get("payload")
        return isinstance(last_payload, Mapping) and all(
            last_payload.get(key) == value for key, value in payload.items()
        )


def _none_if_missing(value: Any) -> Any | None:
    return None if value is _MISSING else value


def _coerce_uuid(value: Any) -> Any:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return value


def _looks_like_agent_run(value: Any) -> bool:
    return value is not None and any(hasattr(value, field) for field in OUTPUT_FIELDS)


def _normalize_tool_call_payload(value: Any) -> dict[str, Any]:
    data = _json_safe(value)
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        return {"value": data}

    payload = dict(data)
    tool_name = payload.get("tool_name") or payload.get("name")
    tool_args = payload.get("tool_args")
    if tool_args is None:
        tool_args = payload.get("arguments")
    if tool_name is not None:
        payload["tool_name"] = str(tool_name)
        payload.setdefault("name", str(tool_name))
    if isinstance(tool_args, Mapping):
        payload["tool_args"] = dict(tool_args)
        payload.setdefault("arguments", dict(tool_args))
    elif tool_args is not None:
        payload["tool_args"] = tool_args
        payload.setdefault("arguments", tool_args)
    return payload


def _has_existing_output(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    return value is not None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"))
        except TypeError:
            return _json_safe(model_dump())

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]

    return str(value)


__all__ = [
    "HARNESS_TRACE_EVENT_NAMES",
    "SHADOW_TRACE_EVENT_NAMES",
    "TRACE_EVENT_NAMES",
    "TraceStore",
]
