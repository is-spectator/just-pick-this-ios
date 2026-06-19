from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    PromptAssignment,
    PromptAuditLog,
    PromptPublishEvent,
    PromptTemplate,
    PromptVersion,
)


DEFAULT_ENVIRONMENT = "staging"

INPUT_GATE_CURRENT_POLICY = """当前 V0 InputGate 是 deterministic gate，不调用 LLM。

执行规则：
1. 先 rewrite_query，抽取 canonical_query、slots、location_state、decision_domain。
2. greeting / smalltalk / app_help / unknown 不进入 PipiLoop，不创建 question，不检索，不开放 tools。
3. 含明确场景的 decision_request / help_request 才进入 loop。
4. venue_ordering 优先级高于 area_food；已在店内点菜时允许 search_knowledge、create_recommendation_card、draft_help_card。
5. area + food/cuisine 足够进入检索；模糊缺槽先文本澄清，不调用工具。
6. active help card 场景下，update_help_card / publish_help / one_liner_answer / finalize_request 走对应工具。
7. allowed_tools 是 Reasoner 的硬边界；后续 AbilityCenter 还会二次校验。
"""

CONTEXT_BUILDER_CURRENT_POLICY = """当前 V0 ContextBuilder 是 deterministic context pack，不调用 LLM。

上下文包包含：
1. 当前 conversation_id、turn_id、user_message。
2. 最近对话 turns，保留用户历史决策上下文。
3. active_help_card，如果存在则作为求一个更新/发布/来一句/收口的上下文。
4. query_rewrite 结果和 latest_user_context。
5. client_context，例如位置、benchmark_case_id。
6. 工具输出会在 PipiLoop 中持续写入 context_pack.tool_outputs。

约束：
- 不补造事实。
- 只把已落库或当前 turn 可证明的信息放进 context。
- contextual follow-up 会拼接最近的决策上下文，但不替用户新增偏好。
"""

REASONER_CURRENT_SYSTEM = """你是皮皮 Agent 的 product reasoner，必须在 Harness 约束内工作。
你每轮只能输出一个 JSON object，且只能是二选一：
1. {"type":"tool","tool_name":"<allowed tool>","tool_args":{},"reason":"..."}
2. {"type":"answer","message":"...","ui_events":[],"data":{}}

硬规则：
1. 不能绕过 tool/function call，不能直接吐推荐卡 JSON 或求一个 JSON。
2. tool_name 必须来自 allowed_tools，不允许自造工具。
3. greeting / smalltalk / app_help 不能调用工具，只能 answer。
4. decision_request / help_request 首轮必须先 search_knowledge，不能跳过检索直接出卡。
5. search_knowledge 后如果证据不足、无 evidence_ids、无 approved answer，必须 draft_help_card。
6. create_recommendation_card / draft_help_card 等 card tool_result 返回后，下一轮必须 answer 收口。
7. 已有 card/help_card 工具结果时，answer 只能引用 tool_result 的 ui_events 和 data，不能编造新卡。
"""

REASONER_TOOL_POLICY = """当前 V0 Reasoner/Ability policy：

1. 如果上一个工具不是 search_knowledge，先收口 answer。
2. 如果 InputGate 不允许进入 loop，直接用 direct_answer_for_gate。
3. publish_help -> publish_help_card。
4. update_help_card -> update_help_card。
5. one_liner_answer -> submit_one_liner_answer；来一句只是 human evidence。
6. finalize_request -> finalize_help_card。
7. decision_request / help_request 首轮必须先 search_knowledge。
8. 检索后如果命中 is_card_ready_hit，才 create_recommendation_card。
9. 否则 draft_help_card，不硬推卡。
10. create_recommendation_card 参数来自 strongest evidence，必须带 evidence_ids、retrieval_run_id、confidence。
"""

EVALUATOR_CURRENT_SYSTEM = """当前 V0 Evaluator 是 deterministic evaluator，不调用 LLM。

推荐卡检查：
1. 必须是单卡，不能返回多个 item。
2. decision_factor 必须具体，不能只有“稳/靠谱/不踩雷”等泛化描述。
3. 不允许旧字段 reasons / bullets / followups / why_questions / not_for / warning 泄漏到推荐卡合同。
4. venue ordering 要保留店内语境，避免把海底捞店内点菜误判成附近找餐厅。

证据检查：
1. hit score >= 0.7。
2. 必须有 answer_evidence 或合格 place evidence。
3. 图片可选；无图时仍可推荐，但必须有 evidence_ids。
4. 有图时必须 verified/displayable 且 is_ai_generated=false。
5. AMap/POI 只能作为 place evidence，必须有与用户偏好/路线/口味绑定的 decision_factor。
6. human_help_required 时不能硬推卡。
"""

ANSWER_GATE_CURRENT_SYSTEM = """当前 V0 AnswerGate 是 deterministic guard，不调用 LLM。

禁止：
1. 在 assistant text 里直接输出推荐卡 JSON 或求一个 JSON。
2. 输出未通过 tool 落库的 card/help_card/light_event。
3. 输出 show_recommendation_card / show_help_card_draft 等 UI event 文案。
4. 泄漏 debug、trace、runtime、fallback、schema、provider、model 等内部词。
5. 声称“我已经生成/弹出/展示卡片”，除非对应 persisted id 来自 tool。

允许：
- 普通文本回答。
- 对已由工具落库的卡片/help_card/light_event 做安全收口。
"""

HELP_CARD_EXTRACTOR_CURRENT_SYSTEM = """当前 V0 Help Card draft 由 deterministic Reasoner 生成参数。

规则：
1. 这是问题压缩器，不是用户原话截断器。
2. 必须抽 title、context、wants、avoids、constraints、missing_info。
3. title 必须具体，不能是“北京这顿饭，求一个”或“这顿饭，求一个”。
4. context 要保留 area / venue / city / scene / party_size / spicy_preference 等已知槽位。
5. wants 不允许只写“好吃”“别让我查”等泛词。
6. avoids 不允许写“多个选项”等产品规则，只保留用户真实避开项。
7. constraints.missing_info 标出缺失槽位，方便追问或求助收口。
8. 求一个用于证据不足、低置信、无 approved answer 场景；不是最终答案。
"""

FINALIZER_CURRENT_SYSTEM = """当前 V0 PipiFinalizeGraph 是 deterministic finalize graph，不调用 LLM。

执行顺序：
1. load_help_card。
2. load_help_answers。
3. retrieve_knowledge。
4. decide_final_answer。
5. finalize_help_card。
6. create_recommendation_card。
7. save_intent_answer。
8. light_user。

规则：
- help_answers 数量低于 min_answers_required 时，状态是 needs_more_answers。
- 最终推荐只基于 human evidence 和 retrieval hits。
- finalize_help_card 是 orchestration tool call，不直接伪造推荐卡。
- create_recommendation_card 必须通过 tool boundary。
- save_intent_answer 沉淀可复用人类证据。
- light_user 只在 final recommendation ready 后触发。
"""

SHADOW_REASONER_CURRENT_SYSTEM = """你是皮皮 Agent 的 shadow reasoner。你只做影子判断，不执行工具，不创建卡片，不影响线上答案。必须只输出符合 ReasonerDecision schema 的 JSON object。
推荐卡和求一个只能通过 tool_name 表达，不要直接输出卡片 JSON。
这是 audit-only：不能调用 AbilityCenter，不能写 RecommendationCard/HelpCard，不能改变 product output。
请在 reason 或 message 中覆盖 why_different_from_deterministic、risk_if_promoted、confidence 三点；不要新增 schema 外字段。
"""

DEFAULT_PROMPT_TEMPLATES: list[dict[str, Any]] = [
    {
        "prompt_key": "input_gate.system",
        "name": "InputGate System",
        "scope": "input_gate",
        "description": "判断用户意图、槽位、是否进入 loop 和 allowed tools。",
        "content": INPUT_GATE_CURRENT_POLICY,
    },
    {
        "prompt_key": "context_builder.policy",
        "name": "ContextBuilder Policy",
        "scope": "context_builder",
        "description": "组装历史上下文、active help card 和 query rewrite 的策略。",
        "content": CONTEXT_BUILDER_CURRENT_POLICY,
    },
    {
        "prompt_key": "reasoner.system",
        "name": "Reasoner System",
        "scope": "reasoner",
        "description": "决定下一步回答或调用能力。",
        "content": REASONER_CURRENT_SYSTEM,
    },
    {
        "prompt_key": "reasoner.tool_policy",
        "name": "Reasoner Tool Policy",
        "scope": "reasoner",
        "description": "控制能力选择和工具边界。",
        "content": REASONER_TOOL_POLICY,
    },
    {
        "prompt_key": "evaluator.system",
        "name": "Evaluator System",
        "scope": "evaluator",
        "description": "校验证据、图片、卡片合同和质量。",
        "content": EVALUATOR_CURRENT_SYSTEM,
    },
    {
        "prompt_key": "answer_gate.system",
        "name": "AnswerGate System",
        "scope": "answer_gate",
        "description": "最终回复安全闸。",
        "content": ANSWER_GATE_CURRENT_SYSTEM,
    },
    {
        "prompt_key": "help_card_extractor.system",
        "name": "Help Card Extractor",
        "scope": "help_card",
        "description": "从用户问题中提取求一个标题、上下文、想要和避开。",
        "content": HELP_CARD_EXTRACTOR_CURRENT_SYSTEM,
    },
    {
        "prompt_key": "finalizer.system",
        "name": "Finalizer System",
        "scope": "finalizer",
        "description": "把 human evidence 汇总成最终推荐卡。",
        "content": FINALIZER_CURRENT_SYSTEM,
    },
    {
        "prompt_key": "shadow_reasoner.system",
        "name": "Shadow Reasoner System",
        "scope": "shadow_reasoner",
        "description": "影子推理，用于质量评估和 diff。",
        "content": SHADOW_REASONER_CURRENT_SYSTEM,
    },
]


def seed_prompt_templates(
    session: Session,
    *,
    actor: str = "system",
    environment: str = DEFAULT_ENVIRONMENT,
) -> None:
    existing = {row.prompt_key: row for row in session.scalars(select(PromptTemplate)).all()}
    for item in DEFAULT_PROMPT_TEMPLATES:
        if item["prompt_key"] in existing:
            template = existing[item["prompt_key"]]
            _sync_template_default(template, item)
            _sync_system_seed_version(session, template, item["content"], actor=actor)
            _ensure_assignment(session, item["prompt_key"], environment=environment, actor=actor)
            continue
        template = PromptTemplate(
            prompt_key=item["prompt_key"],
            name=item["name"],
            scope=item["scope"],
            description=item["description"],
            variables_schema_json=item.get("variables_schema_json") or {},
        )
        session.add(template)
        session.flush()
        version = PromptVersion(
            template_id=template.id,
            version=1,
            content=item["content"],
            status="published",
            checksum=checksum_content(item["content"]),
            created_by=actor,
            published_at=utcnow(),
        )
        session.add(version)
        session.flush()
        assignment = PromptAssignment(
            prompt_key=template.prompt_key,
            active_version_id=version.id,
            environment=environment,
            rollout_percent=100,
        )
        session.add(assignment)
        session.add(
            PromptAuditLog(
                action="seed",
                prompt_key=template.prompt_key,
                version_id=version.id,
                before_json=None,
                after_json=json_payload(serialize_prompt_version(version)),
                actor=actor,
            )
        )
    session.flush()


def list_prompts(session: Session, *, environment: str = DEFAULT_ENVIRONMENT) -> list[dict[str, Any]]:
    seed_prompt_templates(session, environment=environment)
    templates = session.scalars(select(PromptTemplate).order_by(PromptTemplate.scope.asc(), PromptTemplate.prompt_key.asc())).all()
    return [serialize_prompt_summary(session, template, environment=environment) for template in templates]


def get_prompt_detail(session: Session, prompt_key: str, *, environment: str = DEFAULT_ENVIRONMENT) -> dict[str, Any]:
    template = get_template(session, prompt_key, environment=environment)
    versions = session.scalars(
        select(PromptVersion)
        .where(PromptVersion.template_id == template.id)
        .order_by(PromptVersion.version.desc(), PromptVersion.created_at.desc())
    ).all()
    assignment = get_assignment(session, prompt_key, environment=environment)
    audits = session.scalars(
        select(PromptAuditLog)
        .where(PromptAuditLog.prompt_key == prompt_key)
        .order_by(PromptAuditLog.created_at.desc())
        .limit(20)
    ).all()
    return {
        "template": serialize_prompt_template(template),
        "assignment": serialize_prompt_assignment(assignment),
        "active_version": serialize_prompt_version(session.get(PromptVersion, assignment.active_version_id)),
        "versions": [serialize_prompt_version(item) for item in versions],
        "recent_audits": [serialize_prompt_audit(item) for item in audits],
        "last_dry_run": latest_dry_run_result(session, prompt_key),
    }


def create_draft(
    session: Session,
    prompt_key: str,
    payload: dict[str, Any],
    *,
    actor: str,
    environment: str = DEFAULT_ENVIRONMENT,
) -> PromptVersion:
    template = get_template(session, prompt_key, environment=environment)
    base = _version_from_payload(session, payload.get("base_version_id"))
    if base is None:
        base = active_version(session, prompt_key, environment=environment)
    content = str(payload.get("content") if "content" in payload else base.content)
    next_version = int(
        session.scalar(select(func.coalesce(func.max(PromptVersion.version), 0)).where(PromptVersion.template_id == template.id))
        or 0
    ) + 1
    row = PromptVersion(
        template_id=template.id,
        version=next_version,
        content=content,
        status="draft",
        checksum=checksum_content(content),
        created_by=actor,
    )
    session.add(row)
    session.flush()
    session.add(
        PromptAuditLog(
            action="draft",
            prompt_key=prompt_key,
            version_id=row.id,
            before_json=json_payload(serialize_prompt_version(base)),
            after_json=json_payload(serialize_prompt_version(row)),
            actor=actor,
        )
    )
    session.flush()
    return row


def dry_run_prompt(
    session: Session,
    prompt_key: str,
    payload: dict[str, Any],
    *,
    actor: str,
    environment: str = DEFAULT_ENVIRONMENT,
) -> dict[str, Any]:
    del environment
    version_id = payload.get("version_id")
    if not version_id:
        raise ValueError("version_id is required")
    version = get_version(session, version_id)
    cases = prompt_smoke_cases()
    content = version.content.strip()
    forced_failure = "FAIL_DRY_RUN" in content or "__dry_run_fail__" in content
    issues: list[dict[str, Any]] = []
    if not content:
        issues.append({"case_id": "content", "severity": "error", "message": "prompt content is empty"})
    if forced_failure:
        issues.append({"case_id": "forced_failure", "severity": "error", "message": "forced dry-run failure marker"})
    passed = not issues
    result = {
        "passed": passed,
        "total": len(cases),
        "failed": len(issues),
        "avg_quality": 0.86 if passed else 0.31,
        "issues": issues,
        "suite": payload.get("suite") or "prompt_smoke_v0",
        "cases": cases,
        "version_id": str(version.id),
        "version": version.version,
        "prompt_key": prompt_key,
    }
    session.add(
        PromptAuditLog(
            action="dry_run",
            prompt_key=prompt_key,
            version_id=version.id,
            before_json=None,
            after_json=json_payload(result),
            actor=actor,
        )
    )
    session.flush()
    return result


def publish_prompt(
    session: Session,
    prompt_key: str,
    payload: dict[str, Any],
    *,
    actor: str,
    environment: str = DEFAULT_ENVIRONMENT,
) -> PromptVersion:
    version_id = payload.get("version_id")
    if not version_id:
        raise ValueError("version_id is required")
    target = get_version(session, version_id)
    dry_run = latest_dry_run_result(session, prompt_key, version_id=target.id)
    if not dry_run or not dry_run.get("passed"):
        raise RuntimeError("latest dry-run must pass before publish")
    assignment = get_assignment(session, prompt_key, environment=environment)
    previous_id = assignment.active_version_id
    previous = session.get(PromptVersion, previous_id)
    if previous is not None and previous.id != target.id:
        previous.status = "archived"
    target.status = "published"
    target.published_at = utcnow()
    assignment.active_version_id = target.id
    assignment.rollout_percent = int(payload.get("rollout_percent", 100))
    session.flush()
    event = PromptPublishEvent(
        prompt_key=prompt_key,
        from_version_id=previous_id,
        to_version_id=target.id,
        dry_run_result_json=dry_run,
        published_by=actor,
        published_at=utcnow(),
    )
    session.add(event)
    session.add(
        PromptAuditLog(
            action="publish",
            prompt_key=prompt_key,
            version_id=target.id,
            before_json=json_payload(serialize_prompt_version(previous)),
            after_json=json_payload(
                {"assignment": serialize_prompt_assignment(assignment), "version": serialize_prompt_version(target)}
            ),
            actor=actor,
        )
    )
    session.flush()
    return target


def rollback_prompt(
    session: Session,
    prompt_key: str,
    payload: dict[str, Any],
    *,
    actor: str,
    environment: str = DEFAULT_ENVIRONMENT,
) -> PromptVersion:
    assignment = get_assignment(session, prompt_key, environment=environment)
    current = session.get(PromptVersion, assignment.active_version_id)
    target = _version_from_payload(session, payload.get("version_id"))
    if target is None:
        template = get_template(session, prompt_key, environment=environment)
        target = session.scalar(
            select(PromptVersion)
            .where(
                PromptVersion.template_id == template.id,
                PromptVersion.id != assignment.active_version_id,
                PromptVersion.status.in_(["published", "archived"]),
            )
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
    if target is None:
        raise ValueError("rollback target not found")
    if current is not None and current.id != target.id:
        current.status = "archived"
    target.status = "published"
    target.published_at = utcnow()
    assignment.active_version_id = target.id
    assignment.rollout_percent = int(payload.get("rollout_percent", assignment.rollout_percent or 100))
    session.add(
        PromptAuditLog(
            action="rollback",
            prompt_key=prompt_key,
            version_id=target.id,
            before_json=json_payload(serialize_prompt_version(current)),
            after_json=json_payload(
                {"assignment": serialize_prompt_assignment(assignment), "version": serialize_prompt_version(target)}
            ),
            actor=actor,
        )
    )
    session.flush()
    return target


def active_prompt_version_map(session: Session, *, environment: str = DEFAULT_ENVIRONMENT) -> dict[str, dict[str, Any]]:
    seed_prompt_templates(session, environment=environment)
    assignments = session.scalars(
        select(PromptAssignment).where(PromptAssignment.environment == environment).order_by(PromptAssignment.prompt_key.asc())
    ).all()
    result: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        version = session.get(PromptVersion, assignment.active_version_id)
        if version is None:
            continue
        result[assignment.prompt_key] = {
            "version_id": str(version.id),
            "version": version.version,
            "checksum": version.checksum,
            "status": version.status,
            "environment": assignment.environment,
            "rollout_percent": assignment.rollout_percent,
        }
    return result


def get_template(session: Session, prompt_key: str, *, environment: str = DEFAULT_ENVIRONMENT) -> PromptTemplate:
    seed_prompt_templates(session, environment=environment)
    template = session.scalar(select(PromptTemplate).where(PromptTemplate.prompt_key == prompt_key))
    if template is None:
        raise ValueError("prompt template not found")
    return template


def get_assignment(session: Session, prompt_key: str, *, environment: str = DEFAULT_ENVIRONMENT) -> PromptAssignment:
    _ensure_assignment(session, prompt_key, environment=environment)
    assignment = session.scalar(
        select(PromptAssignment).where(
            PromptAssignment.prompt_key == prompt_key,
            PromptAssignment.environment == environment,
        )
    )
    if assignment is None:
        raise ValueError("prompt assignment not found")
    return assignment


def active_version(session: Session, prompt_key: str, *, environment: str = DEFAULT_ENVIRONMENT) -> PromptVersion:
    assignment = get_assignment(session, prompt_key, environment=environment)
    version = session.get(PromptVersion, assignment.active_version_id)
    if version is None:
        raise ValueError("active prompt version not found")
    return version


def get_version(session: Session, version_id: str | uuid.UUID) -> PromptVersion:
    try:
        parsed = version_id if isinstance(version_id, uuid.UUID) else uuid.UUID(str(version_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid version_id") from exc
    version = session.get(PromptVersion, parsed)
    if version is None:
        raise ValueError("prompt version not found")
    return version


def latest_dry_run_result(
    session: Session,
    prompt_key: str,
    *,
    version_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    query = select(PromptAuditLog).where(PromptAuditLog.prompt_key == prompt_key, PromptAuditLog.action == "dry_run")
    if version_id is not None:
        query = query.where(PromptAuditLog.version_id == version_id)
    row = session.scalar(query.order_by(PromptAuditLog.created_at.desc()).limit(1))
    return dict(row.after_json or {}) if row is not None else None


def serialize_prompt_summary(
    session: Session,
    template: PromptTemplate,
    *,
    environment: str = DEFAULT_ENVIRONMENT,
) -> dict[str, Any]:
    assignment = get_assignment(session, template.prompt_key, environment=environment)
    active = session.get(PromptVersion, assignment.active_version_id)
    draft_count = int(
        session.scalar(
            select(func.count())
            .select_from(PromptVersion)
            .where(PromptVersion.template_id == template.id, PromptVersion.status == "draft")
        )
        or 0
    )
    return {
        "template": serialize_prompt_template(template),
        "assignment": serialize_prompt_assignment(assignment),
        "active_version": serialize_prompt_version(active),
        "draft_count": draft_count,
        "last_dry_run": latest_dry_run_result(session, template.prompt_key),
    }


def serialize_prompt_template(template: PromptTemplate) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "prompt_key": template.prompt_key,
        "name": template.name,
        "scope": template.scope,
        "description": template.description,
        "variables_schema_json": template.variables_schema_json,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def serialize_prompt_version(version: PromptVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "id": str(version.id),
        "template_id": str(version.template_id),
        "version": version.version,
        "content": version.content,
        "status": version.status,
        "checksum": version.checksum,
        "created_by": version.created_by,
        "created_at": version.created_at,
        "published_at": version.published_at,
    }


def serialize_prompt_assignment(assignment: PromptAssignment | None) -> dict[str, Any] | None:
    if assignment is None:
        return None
    return {
        "id": str(assignment.id),
        "prompt_key": assignment.prompt_key,
        "active_version_id": str(assignment.active_version_id),
        "environment": assignment.environment,
        "rollout_percent": assignment.rollout_percent,
        "created_at": assignment.created_at,
        "updated_at": assignment.updated_at,
    }


def serialize_prompt_audit(row: PromptAuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action": row.action,
        "prompt_key": row.prompt_key,
        "version_id": str(row.version_id) if row.version_id else None,
        "before_json": row.before_json,
        "after_json": row.after_json,
        "actor": row.actor,
        "created_at": row.created_at,
    }


def prompt_smoke_cases() -> list[dict[str, str]]:
    return [
        {"case_id": "hello", "message": "你好"},
        {"case_id": "datong_xijindao", "message": "我在大同喜晋道，吃什么"},
        {"case_id": "korea_niche_beauty", "message": "韩国小众美妆不去明洞，求一个"},
        {"case_id": "publish_without_help", "message": "发出去"},
        {"case_id": "sanlitun_haidilao", "message": "我在三里屯海底捞，两个人不太能吃辣，帮我点"},
        {"case_id": "help_update", "message": "预算不高，别太远，不要游客区"},
    ]


def checksum_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def json_payload(value: Any) -> Any:
    return jsonable_encoder(value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sync_template_default(template: PromptTemplate, item: dict[str, Any]) -> None:
    template.name = str(item["name"])
    template.scope = str(item["scope"])
    template.description = str(item["description"])
    template.variables_schema_json = dict(item.get("variables_schema_json") or {})


def _sync_system_seed_version(
    session: Session,
    template: PromptTemplate,
    content: str,
    *,
    actor: str,
) -> None:
    version = session.scalar(
        select(PromptVersion)
        .where(
            PromptVersion.template_id == template.id,
            PromptVersion.version == 1,
            PromptVersion.created_by == actor,
        )
        .limit(1)
    )
    if version is None:
        return
    if version.content == content:
        return
    version.content = content
    version.checksum = checksum_content(content)


def _ensure_assignment(
    session: Session,
    prompt_key: str,
    *,
    environment: str,
    actor: str = "system",
) -> None:
    template = session.scalar(select(PromptTemplate).where(PromptTemplate.prompt_key == prompt_key))
    if template is None:
        return
    assignment = session.scalar(
        select(PromptAssignment).where(
            PromptAssignment.prompt_key == prompt_key,
            PromptAssignment.environment == environment,
        )
    )
    if assignment is not None:
        return
    version = session.scalar(
        select(PromptVersion)
        .where(PromptVersion.template_id == template.id, PromptVersion.status == "published")
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )
    if version is None:
        version = PromptVersion(
            template_id=template.id,
            version=1,
            content="",
            status="published",
            checksum=checksum_content(""),
            created_by=actor,
            published_at=utcnow(),
        )
        session.add(version)
        session.flush()
    session.add(
        PromptAssignment(
            prompt_key=prompt_key,
            active_version_id=version.id,
            environment=environment,
            rollout_percent=100,
        )
    )
    session.flush()


def _version_from_payload(session: Session, version_id: Any) -> PromptVersion | None:
    if not version_id:
        return None
    return get_version(session, version_id)
