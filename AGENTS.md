# 就选这个 / 皮皮 Agent 后端

## 核心目标

实现 Python 后端里的“皮皮 Agent Runtime”。

主入口是 `/v1/chat/turn`，不是普通 `/recommend`。

推荐卡、求一个、发出去、来一句、最终答案、亮灯，都应该通过 tool/function call 完成。

## 技术栈

- Python 3.11+
- FastAPI
- LangGraph Python
- SQLAlchemy 2.0
- Alembic
- PostgreSQL
- Pydantic v2
- pytest

## 核心规则

1. 用户输入先作为 conversation turn 落库。
2. 皮皮先检索知识，再决定 tool call。
3. 推荐卡必须绑定 verified 且 is_ai_generated=false 的 image_asset。
4. 没有图、没证据、置信不足时，不要硬推卡，生成“求一个”。
5. “来一句”只是 human evidence，不是最终答案。
6. 求一个累计答案后，由 PipiFinalizeGraph 生成最终推荐卡。
7. 所有 agent_run、tool_call、retrieval_run、retrieval_hit、intent_answer、card、help_card、help_answer、light_event 都要归库。
8. 第一阶段使用 deterministic model adapter，不接真实 LLM。

## 禁止

- 不要做一次性 `/recommend` 作为主入口。
- 不要让模型直接吐推荐卡 JSON 绕过工具。
- 不要只用内存存业务状态。
- 不要用 AI 生成图。