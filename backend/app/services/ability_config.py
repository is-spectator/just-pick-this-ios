from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ability.registry import DEFAULT_TOOL_NAMES, build_default_registry
from app.models import AgentAbilityConfig


ABILITY_INTENTS: dict[str, list[str]] = {
    "search_knowledge": ["decision_request", "help_request"],
    "create_recommendation_card": ["decision_request"],
    "draft_help_card": ["decision_request", "help_request"],
    "update_help_card": ["update_help_card"],
    "publish_help_card": ["publish_help"],
    "submit_one_liner_answer": ["one_liner_answer"],
    "finalize_help_card": ["finalize_request"],
    "save_intent_answer": ["finalize_request"],
    "light_user": ["finalize_request"],
}

ABILITY_NAMES: dict[str, str] = {
    "search_knowledge": "检索知识和证据",
    "create_recommendation_card": "生成推荐卡",
    "draft_help_card": "发起求一个",
    "update_help_card": "更新求一个",
    "publish_help_card": "发布求一个",
    "submit_one_liner_answer": "收集来一句",
    "finalize_help_card": "汇总求一个答案",
    "save_intent_answer": "沉淀答案证据",
    "light_user": "亮灯提醒",
}

ABILITY_DESCRIPTIONS: dict[str, str] = {
    "search_knowledge": "先查知识、POI、图片和历史证据，不直接产出卡片。",
    "create_recommendation_card": "在证据和图片满足条件时创建推荐卡。",
    "draft_help_card": "证据不足、无图或低置信时创建“求一个”。",
    "update_help_card": "把用户补充约束写入当前求一个。",
    "publish_help_card": "把草稿求一个发布给其他用户回答。",
    "submit_one_liner_answer": "把“来一句”作为 human evidence 记录，不当作最终答案。",
    "finalize_help_card": "求一个答案达到阈值后进入最终推荐流程。",
    "save_intent_answer": "把可复用答案沉淀为 intent answer 证据。",
    "light_user": "最终卡或重要状态变化后向用户亮灯。",
}


def list_ability_configs(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(select(AgentAbilityConfig).order_by(AgentAbilityConfig.key.asc())).all()
    by_key = {row.key: row for row in rows}
    items: list[dict[str, Any]] = []
    for key in DEFAULT_TOOL_NAMES:
        row = by_key.pop(key, None)
        if row is not None:
            items.append(serialize_ability_config(row, source="db"))
        else:
            items.append(default_ability_config(key))
    for row in by_key.values():
        items.append(serialize_ability_config(row, source="db"))
    return items


def upsert_ability_config(session: Session, key: str, payload: dict[str, Any], *, actor: str) -> AgentAbilityConfig:
    row = session.scalar(select(AgentAbilityConfig).where(AgentAbilityConfig.key == key))
    default = default_ability_config(key)
    if row is None:
        row = AgentAbilityConfig(
            key=key,
            name=str(payload.get("name") or default["name"]),
            ability_type=str(payload.get("ability_type") or default["ability_type"]),
            tool_name=_optional_str(payload.get("tool_name", default.get("tool_name"))),
            description=str(payload.get("description") or default["description"]),
            enabled=bool(payload.get("enabled", default["enabled"])),
            runtime_enabled=bool(payload.get("runtime_enabled", default["runtime_enabled"])),
            trigger_intents_json=list(payload.get("trigger_intents_json") or default["trigger_intents_json"]),
            input_schema_json=dict(payload.get("input_schema_json") or default["input_schema_json"]),
            output_contract_json=dict(payload.get("output_contract_json") or default["output_contract_json"]),
            guardrails_json=dict(payload.get("guardrails_json") or default["guardrails_json"]),
            prompt_keys_json=list(payload.get("prompt_keys_json") or default["prompt_keys_json"]),
            config_json=dict(payload.get("config_json") or default["config_json"]),
            updated_by=actor,
            notes=payload.get("notes") or default.get("notes"),
        )
        session.add(row)
    else:
        if "name" in payload:
            row.name = str(payload["name"])
        if "ability_type" in payload:
            row.ability_type = str(payload["ability_type"])
        if "tool_name" in payload:
            row.tool_name = _optional_str(payload["tool_name"])
        if "description" in payload:
            row.description = str(payload["description"] or "")
        if "enabled" in payload:
            row.enabled = bool(payload["enabled"])
        if "runtime_enabled" in payload:
            row.runtime_enabled = bool(payload["runtime_enabled"])
        if "trigger_intents_json" in payload:
            row.trigger_intents_json = list(payload["trigger_intents_json"] or [])
        if "input_schema_json" in payload:
            row.input_schema_json = dict(payload["input_schema_json"] or {})
        if "output_contract_json" in payload:
            row.output_contract_json = dict(payload["output_contract_json"] or {})
        if "guardrails_json" in payload:
            row.guardrails_json = dict(payload["guardrails_json"] or {})
        if "prompt_keys_json" in payload:
            row.prompt_keys_json = list(payload["prompt_keys_json"] or [])
        if "config_json" in payload:
            row.config_json = dict(payload["config_json"] or {})
        if "notes" in payload:
            row.notes = payload["notes"]
        row.version += 1
        row.updated_by = actor
    session.flush()
    return row


def filter_enabled_ability_tools(session: Session, allowed_tools: list[str]) -> list[str]:
    if not allowed_tools:
        return []
    rows = session.scalars(
        select(AgentAbilityConfig).where(AgentAbilityConfig.tool_name.in_(allowed_tools))
    ).all()
    by_tool = {row.tool_name: row for row in rows if row.tool_name}
    filtered: list[str] = []
    for tool_name in allowed_tools:
        row = by_tool.get(tool_name)
        if row is not None and (not row.enabled or not row.runtime_enabled):
            continue
        filtered.append(tool_name)
    return filtered


def serialize_ability_config(row: AgentAbilityConfig, *, source: str) -> dict[str, Any]:
    item = {
        "id": str(row.id),
        "key": row.key,
        "name": row.name,
        "ability_type": row.ability_type,
        "tool_name": row.tool_name,
        "description": row.description,
        "enabled": row.enabled,
        "runtime_enabled": row.runtime_enabled,
        "trigger_intents_json": row.trigger_intents_json,
        "input_schema_json": row.input_schema_json,
        "output_contract_json": row.output_contract_json,
        "guardrails_json": row.guardrails_json,
        "prompt_keys_json": row.prompt_keys_json,
        "config_json": row.config_json,
        "version": row.version,
        "updated_by": row.updated_by,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "source": source,
    }
    return {**item, **_runtime_flags(item)}


def default_ability_config(key: str) -> dict[str, Any]:
    registry = build_default_registry()
    tool = registry.get(key)
    schema = tool.input_schema.model_json_schema() if tool is not None and tool.input_schema is not None else {}
    item = {
        "id": None,
        "key": key,
        "name": ABILITY_NAMES.get(key, key),
        "ability_type": "builtin_tool" if key in DEFAULT_TOOL_NAMES else "custom_skill",
        "tool_name": key if key in DEFAULT_TOOL_NAMES else None,
        "description": ABILITY_DESCRIPTIONS.get(key, ""),
        "enabled": True,
        "runtime_enabled": key in DEFAULT_TOOL_NAMES,
        "trigger_intents_json": ABILITY_INTENTS.get(key, []),
        "input_schema_json": schema,
        "output_contract_json": {},
        "guardrails_json": {},
        "prompt_keys_json": ["area_food_evidence_policy"] if key == "search_knowledge" else [],
        "config_json": {},
        "version": 0,
        "updated_by": None,
        "notes": None,
        "created_at": None,
        "updated_at": None,
        "source": "default",
    }
    return {**item, **_runtime_flags(item)}


def _runtime_flags(item: dict[str, Any]) -> dict[str, Any]:
    registry = build_default_registry()
    tool_name = item.get("tool_name")
    runtime_registered = isinstance(tool_name, str) and tool_name in registry
    return {
        "runtime_registered": runtime_registered,
        "runtime_status": "active"
        if item.get("enabled") and item.get("runtime_enabled") and runtime_registered
        else "draft" if not runtime_registered else "disabled",
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
