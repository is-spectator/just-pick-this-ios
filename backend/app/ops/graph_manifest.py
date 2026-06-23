from __future__ import annotations

from typing import Any


GRAPH_NODES: list[dict[str, Any]] = [
    {
        "id": "chat_api",
        "type": "api",
        "label": "Chat API",
        "description": "主入口 /v1/chat/turn，接收用户 turn。",
    },
    {
        "id": "input_gate",
        "type": "harness",
        "label": "InputGate",
        "description": "识别 intent、slots、是否进入 loop 和 allowed tools。",
        "prompt_key": "input_gate.system",
    },
    {
        "id": "direct_answer",
        "type": "output",
        "label": "Direct Answer",
        "description": "问候、帮助等不进入 loop 的直接回复。",
    },
    {
        "id": "context_builder",
        "type": "harness",
        "label": "ContextBuilder",
        "description": "组装历史、active help card、query rewrite 和上下文包。",
        "prompt_key": "context_builder.policy",
    },
    {
        "id": "pipi_loop",
        "type": "reasoner",
        "label": "PipiLoop",
        "description": "多轮 reasoner/tool/evaluator 循环。",
    },
    {
        "id": "reasoner",
        "type": "reasoner",
        "label": "Reasoner",
        "description": "决定下一步是回答还是调用能力。",
        "prompt_key": "reasoner.system",
    },
    {
        "id": "ability_center",
        "type": "tool",
        "label": "AbilityCenter",
        "description": "工具能力边界，校验 allowed_tools 并执行真实能力。",
        "prompt_key": "reasoner.tool_policy",
    },
    {
        "id": "search_knowledge",
        "type": "tool",
        "label": "Tool: search_knowledge",
        "description": "检索知识、POI、图片和历史证据。",
    },
    {
        "id": "create_recommendation_card",
        "type": "tool",
        "label": "Tool: create_recommendation_card",
        "description": "证据和图片满足条件时创建推荐卡。",
    },
    {
        "id": "draft_help_card",
        "type": "tool",
        "label": "Tool: draft_help_card",
        "description": "证据不足、无图或低置信时创建求一个。",
        "prompt_key": "help_card_extractor.system",
    },
    {
        "id": "update_help_card",
        "type": "tool",
        "label": "Tool: update_help_card",
        "description": "把用户新增约束写入 active help card。",
    },
    {
        "id": "publish_help_card",
        "type": "tool",
        "label": "Tool: publish_help_card",
        "description": "发布求一个，进入人类回答收集。",
    },
    {
        "id": "submit_one_liner_answer",
        "type": "tool",
        "label": "Tool: submit_one_liner_answer",
        "description": "记录来一句作为 human evidence。",
    },
    {
        "id": "evaluator",
        "type": "evaluator",
        "label": "Evaluator",
        "description": "校验证据、卡片合同、图片和质量。",
        "prompt_key": "evaluator.system",
    },
    {
        "id": "answer_gate",
        "type": "evaluator",
        "label": "AnswerGate",
        "description": "最终回复闸门，禁止绕过工具链输出卡片 JSON。",
        "prompt_key": "answer_gate.system",
    },
    {
        "id": "trace_store",
        "type": "storage",
        "label": "TraceStore",
        "description": "持久化 loop_trace、tool call、retrieval 和 gate 结果。",
    },
    {
        "id": "intent_answer_memory",
        "type": "storage",
        "label": "Memory / IntentAnswer",
        "description": "沉淀可复用的人类证据和最终答案。",
    },
    {
        "id": "finalize_graph",
        "type": "harness",
        "label": "PipiFinalizeGraph",
        "description": "求一个答案达到阈值后的最终推荐编排。",
        "prompt_key": "finalizer.system",
    },
    {
        "id": "light_user",
        "type": "output",
        "label": "LightEvent",
        "description": "最终推荐或关键状态变化后亮灯提醒。",
    },
    {
        "id": "shadow_reasoner",
        "type": "reasoner",
        "label": "Shadow Reasoner",
        "description": "影子推理链路，用于评测和 diff，不影响线上输出。",
        "prompt_key": "shadow_reasoner.system",
    },
]

GRAPH_EDGES: list[dict[str, str]] = [
    {"id": "chat_api-input_gate", "source": "chat_api", "target": "input_gate", "label": "user_turn"},
    {"id": "input_gate-direct_answer", "source": "input_gate", "target": "direct_answer", "label": "no_loop"},
    {"id": "input_gate-context_builder", "source": "input_gate", "target": "context_builder", "label": "enter_loop"},
    {"id": "context_builder-pipi_loop", "source": "context_builder", "target": "pipi_loop", "label": "context_pack"},
    {"id": "pipi_loop-reasoner", "source": "pipi_loop", "target": "reasoner", "label": "iterate"},
    {"id": "reasoner-ability_center", "source": "reasoner", "target": "ability_center", "label": "tool"},
    {"id": "ability_center-search_knowledge", "source": "ability_center", "target": "search_knowledge", "label": "tool_call"},
    {
        "id": "ability_center-create_recommendation_card",
        "source": "ability_center",
        "target": "create_recommendation_card",
        "label": "tool_call",
    },
    {"id": "ability_center-draft_help_card", "source": "ability_center", "target": "draft_help_card", "label": "tool_call"},
    {"id": "ability_center-update_help_card", "source": "ability_center", "target": "update_help_card", "label": "tool_call"},
    {"id": "ability_center-publish_help_card", "source": "ability_center", "target": "publish_help_card", "label": "tool_call"},
    {
        "id": "ability_center-submit_one_liner_answer",
        "source": "ability_center",
        "target": "submit_one_liner_answer",
        "label": "tool_call",
    },
    {"id": "search_knowledge-evaluator", "source": "search_knowledge", "target": "evaluator", "label": "tool_result"},
    {
        "id": "create_recommendation_card-evaluator",
        "source": "create_recommendation_card",
        "target": "evaluator",
        "label": "tool_result",
    },
    {"id": "draft_help_card-evaluator", "source": "draft_help_card", "target": "evaluator", "label": "tool_result"},
    {"id": "evaluator-reasoner", "source": "evaluator", "target": "reasoner", "label": "continue"},
    {"id": "reasoner-answer_gate", "source": "reasoner", "target": "answer_gate", "label": "answer"},
    {"id": "answer_gate-trace_store", "source": "answer_gate", "target": "trace_store", "label": "persist"},
    {
        "id": "submit_one_liner_answer-finalize_graph",
        "source": "submit_one_liner_answer",
        "target": "finalize_graph",
        "label": "ready",
    },
    {
        "id": "finalize_graph-intent_answer_memory",
        "source": "finalize_graph",
        "target": "intent_answer_memory",
        "label": "save_intent_answer",
    },
    {"id": "finalize_graph-light_user", "source": "finalize_graph", "target": "light_user", "label": "light_user"},
]


def graph_manifest(prompt_versions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for node in GRAPH_NODES:
        prompt_key = node.get("prompt_key")
        active = prompt_versions.get(prompt_key) if isinstance(prompt_key, str) else None
        nodes.append(
            {
                **node,
                "status": "ok",
                "active_prompt_version": active,
                "stats": {"recent_errors": 0, "avg_latency_ms": None, "recent_trace_count": 0},
            }
        )
    return {"nodes": nodes, "edges": GRAPH_EDGES}
