from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.harness.input_gate import run_input_gate
from app.models import AgentPromptConfig, AgentPromptConfigVersion, PromptReplayRun, Turn


DEFAULT_PROMPT_CONFIGS: dict[str, dict[str, Any]] = {
    "area_food_evidence_policy": {
        "key": "area_food_evidence_policy",
        "name": "到区域选店证据策略",
        "prompt_type": "evidence_policy",
        "content": (
            "先尊重用户显式偏好、身份线索、同行关系和口味禁忌，再考虑距离。"
            "profile_cuisine_rules 会影响 AMap POI keyword、候选 rerank、reject filter 和 decision_factor 前缀。"
        ),
        "config_json": {
            "generic_food_keyword": "餐饮",
            "profile_cuisine_rules": [
                {
                    "name": "cantonese_profile",
                    "when_any": ["广东人", "广州人", "深圳人", "粤", "广东口味"],
                    "search_keyword": "粤菜",
                    "display_food": "粤菜",
                    "decision_prefix": "你说自己是广东人，先按粤菜/清淡口味筛一遍。",
                    "prefer_terms": ["粤", "广东", "广州", "潮汕", "茶餐厅", "广式", "顺德", "港式"],
                    "reject_terms": ["长沙", "湘菜", "川菜", "麻辣", "重辣", "火锅"],
                    "require_preferred_match": True,
                },
                {
                    "name": "non_spicy_profile",
                    "when_any": ["不吃辣", "不能吃辣", "不太能吃辣", "少辣", "不要辣"],
                    "search_keyword": "清淡餐厅",
                    "display_food": "清淡口味",
                    "decision_prefix": "你说不太能吃辣，先避开重辣和红油火锅。",
                    "prefer_terms": ["清淡", "粤", "杭帮", "本帮", "淮扬", "潮汕", "茶餐厅", "汤", "蒸"],
                    "reject_terms": ["重辣", "麻辣", "辣锅", "红油", "川菜", "湘菜", "火锅", "烧烤"],
                    "require_preferred_match": True,
                },
                {
                    "name": "jiangzhe_profile",
                    "when_any": ["江浙", "浙江人", "杭州人", "上海人", "南京人", "苏州人", "清淡", "本帮", "杭帮", "淮扬"],
                    "search_keyword": "杭帮菜",
                    "display_food": "清淡江浙口味",
                    "decision_prefix": "按江浙/清淡口味，先找本帮、杭帮或淮扬这类更稳的店。",
                    "prefer_terms": ["本帮", "杭帮", "淮扬", "江浙", "苏帮", "清淡", "上海", "杭州"],
                    "reject_terms": ["麻辣", "重辣", "湘菜", "川菜", "火锅"],
                    "require_preferred_match": True,
                },
                {
                    "name": "sichuan_profile",
                    "when_any": ["四川人", "成都人", "川渝", "川菜", "想吃辣", "能吃辣"],
                    "search_keyword": "川菜",
                    "display_food": "川菜",
                    "decision_prefix": "你想吃川菜，先选川味明确、不是泛餐饮的店。",
                    "prefer_terms": ["川菜", "四川", "成都", "川渝", "钵钵鸡", "江湖菜"],
                    "reject_terms": ["粤菜", "茶餐厅", "清真", "日料", "轻食"],
                    "require_preferred_match": True,
                },
                {
                    "name": "dongbei_profile",
                    "when_any": ["东北人", "东北菜", "锅包肉", "想吃东北", "家常菜"],
                    "search_keyword": "东北菜",
                    "display_food": "东北菜",
                    "decision_prefix": "按东北口味，先找锅包肉、家常菜这类更对题的店。",
                    "prefer_terms": ["东北", "锅包肉", "铁锅炖", "家常菜", "饺子"],
                    "reject_terms": ["粤菜", "茶餐厅", "日料", "轻食"],
                    "require_preferred_match": True,
                },
                {
                    "name": "vegetarian_profile",
                    "when_any": ["素食", "吃素", "不吃肉", "素菜", "素餐"],
                    "search_keyword": "素食",
                    "display_food": "素食",
                    "decision_prefix": "你有素食需求，先找素食/素菜明确的店。",
                    "prefer_terms": ["素食", "素菜", "素餐", "蔬食", "斋"],
                    "reject_terms": ["烤肉", "烧烤", "火锅", "肉", "牛羊", "海鲜"],
                    "require_preferred_match": True,
                },
                {
                    "name": "parents_profile",
                    "when_any": ["带爸妈", "带父母", "和爸妈", "和父母", "带长辈", "家庭"],
                    "search_keyword": "家常菜",
                    "display_food": "适合长辈",
                    "decision_prefix": "带爸妈吃饭，优先安静、清淡、不折腾和少排队。",
                    "prefer_terms": ["家常", "清淡", "包间", "安静", "长辈", "不排队"],
                    "reject_terms": ["重辣", "酒吧", "夜店", "排队", "网红", "吵", "站着"],
                    "require_preferred_match": False,
                },
                {
                    "name": "date_profile",
                    "when_any": ["约会", "对象", "女朋友", "男朋友", "纪念日", "暧昧"],
                    "search_keyword": "约会餐厅",
                    "display_food": "适合约会",
                    "decision_prefix": "约会场景优先安静、氛围和不用久排。",
                    "prefer_terms": ["约会", "氛围", "安静", "景观", "环境", "不排队"],
                    "reject_terms": ["排队", "吵", "快餐", "大排档", "重油", "重辣"],
                    "require_preferred_match": False,
                },
                {
                    "name": "solo_profile",
                    "when_any": ["一个人", "单人", "自己吃", "我一个", "独自"],
                    "search_keyword": "单人餐",
                    "display_food": "单人友好",
                    "decision_prefix": "一个人吃饭，优先快、近、单人友好。",
                    "prefer_terms": ["单人", "简餐", "快餐", "面", "粉", "饭", "小吃"],
                    "reject_terms": ["大桌", "包间", "宴会", "排队"],
                    "require_preferred_match": False,
                },
            ],
        },
        "version": 0,
        "enabled": True,
        "source": "default",
    }
}


def list_prompt_configs(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(select(AgentPromptConfig).order_by(AgentPromptConfig.key.asc())).all()
    seen = {row.key for row in rows}
    items = [_serialize_prompt(row, source="db") for row in rows]
    for key, default in DEFAULT_PROMPT_CONFIGS.items():
        if key not in seen:
            items.append(default.copy())
    return items


def get_prompt_config(session: Session, key: str) -> dict[str, Any]:
    row = session.scalar(
        select(AgentPromptConfig).where(
            AgentPromptConfig.key == key,
            AgentPromptConfig.enabled.is_(True),
        )
    )
    if row is not None:
        return _serialize_prompt(row, source="db")
    return DEFAULT_PROMPT_CONFIGS[key].copy()


def upsert_prompt_config(session: Session, key: str, payload: dict[str, Any], *, actor: str) -> AgentPromptConfig:
    row = session.scalar(select(AgentPromptConfig).where(AgentPromptConfig.key == key))
    if row is None:
        default = DEFAULT_PROMPT_CONFIGS.get(key, {})
        row = AgentPromptConfig(
            key=key,
            name=str(payload.get("name") or default.get("name") or key),
            prompt_type=str(payload.get("prompt_type") or default.get("prompt_type") or "policy"),
            content=str(payload.get("content") or default.get("content") or ""),
            config_json=dict(payload.get("config_json") or default.get("config_json") or {}),
            enabled=bool(payload.get("enabled", True)),
            version=1,
            updated_by=actor,
            notes=payload.get("notes") or default.get("notes"),
        )
        session.add(row)
        session.flush()
        _create_prompt_version(
            session,
            row,
            actor=actor,
            change_reason=str(payload.get("change_reason") or payload.get("notes") or "created"),
        )
    else:
        _create_prompt_version(
            session,
            row,
            actor=row.updated_by or actor,
            change_reason="backfilled before update",
        )
        if "name" in payload:
            row.name = str(payload["name"])
        if "prompt_type" in payload:
            row.prompt_type = str(payload["prompt_type"])
        if "content" in payload:
            row.content = str(payload["content"])
        if "config_json" in payload:
            row.config_json = dict(payload["config_json"] or {})
        if "enabled" in payload:
            row.enabled = bool(payload["enabled"])
        if "notes" in payload:
            row.notes = payload["notes"]
        row.version += 1
        row.updated_by = actor
        session.flush()
        _create_prompt_version(
            session,
            row,
            actor=actor,
            change_reason=str(payload.get("change_reason") or payload.get("notes") or "updated"),
        )
    return row


def list_prompt_versions(session: Session, key: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(AgentPromptConfigVersion)
        .where(AgentPromptConfigVersion.prompt_key == key)
        .order_by(AgentPromptConfigVersion.version.desc(), AgentPromptConfigVersion.created_at.desc())
    ).all()
    return [_serialize_prompt_version(row) for row in rows]


def rollback_prompt_config(
    session: Session,
    key: str,
    *,
    version: int,
    actor: str,
    notes: str | None = None,
) -> AgentPromptConfig:
    target = session.scalar(
        select(AgentPromptConfigVersion).where(
            AgentPromptConfigVersion.prompt_key == key,
            AgentPromptConfigVersion.version == version,
        )
    )
    if target is None:
        raise ValueError("prompt version not found")
    payload = {
        "name": target.name,
        "prompt_type": target.prompt_type,
        "content": target.content,
        "config_json": target.config_json or {},
        "enabled": target.enabled,
        "notes": notes or f"rollback to v{version}",
        "change_reason": f"rollback to v{version}",
    }
    return upsert_prompt_config(session, key, payload, actor=actor)


def run_prompt_replay(session: Session, key: str, payload: dict[str, Any], *, actor: str) -> PromptReplayRun:
    active = _get_admin_prompt_config(session, key)
    candidate = _candidate_config(active, payload)
    cases = _replay_cases(session, payload)
    input_json = {
        "prompt_key": key,
        "prompt_version": active.get("version"),
        "candidate_version": candidate.get("version"),
        "cases": cases,
        "candidate": {
            "content": candidate.get("content"),
            "config_json": candidate.get("config_json") or {},
            "enabled": candidate.get("enabled"),
        },
    }
    run = PromptReplayRun(
        prompt_key=key,
        prompt_version=int(active.get("version") or 0),
        candidate_version=int(candidate.get("version") or 0),
        admin_actor=actor,
        status="running",
        input_json=input_json,
    )
    session.add(run)
    session.flush()
    try:
        output = _replay_output(cases, active=active, candidate=candidate)
        run.status = "succeeded"
        run.output_json = output
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:1000]
        run.output_json = {"error": run.error_message}
    session.flush()
    return run


def _serialize_prompt(row: AgentPromptConfig, *, source: str) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "key": row.key,
        "name": row.name,
        "prompt_type": row.prompt_type,
        "content": row.content,
        "config_json": row.config_json or {},
        "version": row.version,
        "enabled": row.enabled,
        "updated_by": row.updated_by,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "source": source,
    }


def _get_admin_prompt_config(session: Session, key: str) -> dict[str, Any]:
    row = session.scalar(select(AgentPromptConfig).where(AgentPromptConfig.key == key))
    if row is not None:
        return _serialize_prompt(row, source="db")
    return get_prompt_config(session, key)


def _serialize_prompt_version(row: AgentPromptConfigVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "prompt_config_id": str(row.prompt_config_id) if row.prompt_config_id else None,
        "key": row.prompt_key,
        "version": row.version,
        "name": row.name,
        "prompt_type": row.prompt_type,
        "content": row.content,
        "config_json": row.config_json or {},
        "enabled": row.enabled,
        "updated_by": row.updated_by,
        "notes": row.notes,
        "change_reason": row.change_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_replay(row: PromptReplayRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "prompt_key": row.prompt_key,
        "prompt_version": row.prompt_version,
        "candidate_version": row.candidate_version,
        "admin_actor": row.admin_actor,
        "status": row.status,
        "input_json": row.input_json or {},
        "output_json": row.output_json or {},
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_prompt_replay(row: PromptReplayRun) -> dict[str, Any]:
    return _serialize_replay(row)


def _create_prompt_version(
    session: Session,
    row: AgentPromptConfig,
    *,
    actor: str,
    change_reason: str | None,
) -> None:
    existing = session.scalar(
        select(AgentPromptConfigVersion).where(
            AgentPromptConfigVersion.prompt_key == row.key,
            AgentPromptConfigVersion.version == row.version,
        )
    )
    if existing is not None:
        return
    session.add(
        AgentPromptConfigVersion(
            prompt_config_id=row.id,
            prompt_key=row.key,
            version=row.version,
            name=row.name,
            prompt_type=row.prompt_type,
            content=row.content,
            config_json=dict(row.config_json or {}),
            enabled=row.enabled,
            updated_by=actor,
            notes=row.notes,
            change_reason=change_reason,
        )
    )
    session.flush()


def _candidate_config(active: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    draft = dict(payload.get("candidate") or payload.get("draft") or {})
    candidate = {
        **active,
        **{key: value for key, value in draft.items() if key in {"content", "config_json", "enabled", "name"}},
    }
    if "content" in payload:
        candidate["content"] = payload["content"]
    if "config_json" in payload:
        candidate["config_json"] = payload["config_json"] or {}
    candidate["version"] = int(active.get("version") or 0) + 1
    return candidate


def _replay_cases(session: Session, payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_cases = payload.get("cases")
    cases: list[dict[str, Any]] = []
    if isinstance(raw_cases, list):
        for index, item in enumerate(raw_cases, start=1):
            if not isinstance(item, dict):
                continue
            case = _case_from_payload_item(session, item, index=index)
            if case is not None:
                cases.append(case)
    elif payload.get("turn_id"):
        case = _case_from_payload_item(session, {"turn_id": payload["turn_id"]}, index=1)
        if case is not None:
            cases.append(case)
    elif payload.get("message"):
        cases.append({"case_id": "manual-1", "message": str(payload["message"]), "source": "manual"})

    if not cases:
        limit = min(max(int(payload.get("limit") or 10), 1), 25)
        turns = session.scalars(
            select(Turn)
            .where(Turn.role == "user")
            .order_by(Turn.created_at.desc())
            .limit(limit)
        ).all()
        cases = [
            {
                "case_id": f"turn-{turn.id}",
                "turn_id": str(turn.id),
                "conversation_id": str(turn.conversation_id),
                "message": turn.content,
                "source": "recent_turn",
            }
            for turn in turns
        ]
    return cases[:25]


def _case_from_payload_item(session: Session, item: dict[str, Any], *, index: int) -> dict[str, Any] | None:
    if item.get("turn_id"):
        try:
            turn_id = uuid.UUID(str(item["turn_id"]))
        except ValueError:
            return None
        turn = session.get(Turn, turn_id)
        if turn is None:
            return None
        return {
            "case_id": str(item.get("case_id") or f"turn-{turn.id}"),
            "turn_id": str(turn.id),
            "conversation_id": str(turn.conversation_id),
            "message": turn.content,
            "source": "turn",
        }
    if item.get("message"):
        return {
            "case_id": str(item.get("case_id") or f"manual-{index}"),
            "message": str(item["message"]),
            "source": "manual",
        }
    return None


def _replay_output(
    cases: list[dict[str, Any]],
    *,
    active: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    items = []
    for case in cases:
        message = str(case.get("message") or "")
        gate = run_input_gate(message)
        active_policy = _policy_hit(message, active)
        candidate_policy = _policy_hit(message, candidate)
        changed = active_policy != candidate_policy
        items.append(
            {
                **case,
                "input_gate": gate.model_dump(mode="json"),
                "active_policy": active_policy,
                "candidate_policy": candidate_policy,
                "changed": changed,
            }
        )
    return {
        "summary": _replay_summary(items),
        "cases": items,
    }


def _replay_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    intent_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    loop_entry_count = 0
    changed_count = 0
    for item in items:
        gate = dict(item.get("input_gate") or {})
        intent = str(gate.get("intent_type") or "unknown")
        route = str(gate.get("route_priority") or "none")
        intent_counts[intent] = intent_counts.get(intent, 0) + 1
        route_counts[route] = route_counts.get(route, 0) + 1
        if gate.get("should_enter_loop"):
            loop_entry_count += 1
        if item.get("changed"):
            changed_count += 1
    return {
        "case_count": len(items),
        "loop_entry_count": loop_entry_count,
        "changed_policy_count": changed_count,
        "intent_counts": intent_counts,
        "route_counts": route_counts,
    }


def _policy_hit(message: str, config: dict[str, Any]) -> dict[str, Any]:
    config_json = dict(config.get("config_json") or {})
    rules = config_json.get("profile_cuisine_rules") or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        terms = [str(term) for term in rule.get("when_any") or []]
        if any(term and term in message for term in terms):
            return {
                "matched": True,
                "rule": rule.get("name"),
                "search_keyword": rule.get("search_keyword"),
                "display_food": rule.get("display_food"),
                "require_preferred_match": bool(rule.get("require_preferred_match")),
            }
    return {
        "matched": False,
        "rule": None,
        "search_keyword": config_json.get("generic_food_keyword"),
        "display_food": None,
        "require_preferred_match": False,
    }
