"""Deterministic model adapter for PipiChatGraph V0.

This module deliberately does not connect to a real LLM. It centralizes the
rule-based choices so graph nodes stay small and are easy to replace later.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.state import (
    PipiChatGraphState,
    PipiNextAction,
    RetrievalHit,
    ToolCallDraft,
)


HELP_KEYWORDS = ("求一个", "帮我问", "问问", "谁知道", "help")
PUBLISH_KEYWORDS = ("发出去", "发个求助", "发布", "投出去")
FINALIZE_KEYWORDS = ("总结", "最终", "final", "finalize")
EVIDENCE_KEYWORDS = ("来一句", "补充", "我觉得", "evidence")
RECOMMEND_KEYWORDS = ("推荐", "选哪个", "哪个好", "pick", "choose")
DATONG_KEYWORDS = ("大同", "喜晋道")


@dataclass(frozen=True)
class DeterministicPipiModelAdapter:
    """Rule-based adapter used until a real model layer is approved."""

    min_recommendation_score: float = 0.7

    def decide_next_action(self, state: PipiChatGraphState) -> tuple[PipiNextAction, ToolCallDraft | None]:
        """Pick the next graph action while preserving only one tool-call round."""

        message = state["user_message"].strip()
        normalized = message.lower()
        hits = state.get("retrieval_hits", [])
        metadata = state.get("metadata", {})

        if any(keyword in normalized for keyword in PUBLISH_KEYWORDS):
            return "call_tool", {
                "name": "publish_help_card",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                    "help_card_id": metadata.get("help_card_id") or metadata.get("active_help_card_id"),
                },
                "reason": "User approved publishing the active help card.",
            }

        if any(keyword in normalized for keyword in EVIDENCE_KEYWORDS):
            return "call_tool", {
                "name": "record_human_evidence",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                    "content": message,
                },
                "reason": "User supplied human evidence; it should be recorded, not finalized.",
            }

        if any(keyword in normalized for keyword in FINALIZE_KEYWORDS):
            return "call_tool", {
                "name": "finalize_recommendation",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                },
                "reason": "User asked for a final answer after help/evidence collection.",
            }

        if any(keyword in normalized for keyword in HELP_KEYWORDS):
            return "call_tool", {
                "name": "create_help_card",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                    "question": message,
                },
                "reason": "User explicitly asked for human help, so draft a help card.",
            }

        if any(keyword in message for keyword in DATONG_KEYWORDS) and self._has_card_ready_evidence(hits):
            return "call_tool", {
                "name": "create_recommendation_card",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                    "retrieval_hit_ids": [hit.get("source_id") for hit in hits if hit.get("source_id")],
                },
                "reason": "Datong/Xijindao has verified non-AI image evidence in curated data.",
            }

        if self._has_card_ready_evidence(hits):
            return "call_tool", {
                "name": "create_recommendation_card",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                    "retrieval_hit_ids": [hit.get("source_id") for hit in hits if hit.get("source_id")],
                },
                "reason": "Verified non-AI image evidence and confidence are sufficient for a card.",
            }

        if any(keyword in normalized for keyword in HELP_KEYWORDS + RECOMMEND_KEYWORDS):
            return "call_tool", {
                "name": "create_help_card",
                "arguments": {
                    "conversation_id": state["conversation_id"],
                    "user_turn_id": state["user_turn_id"],
                    "question": message,
                },
                "reason": "Evidence, image verification, or confidence is insufficient; ask humans.",
            }

        return "respond", None

    def compose_response(self, state: PipiChatGraphState) -> str:
        """Create a deterministic assistant message from the completed state."""

        tool_call = state.get("tool_call")
        execution = state.get("tool_execution")

        if tool_call is None:
            return "皮皮已记录这一轮，会先补足证据再推进。"

        tool_name = tool_call.get("name", "")
        status = (execution or {}).get("status", "skipped")

        if status == "succeeded":
            return self._success_message(tool_name)
        if status == "unavailable":
            return f"皮皮已决定调用 {tool_name}，但对应工具服务还没接入。"
        if status == "failed":
            return f"皮皮调用 {tool_name} 时失败，已保留本轮决策供后续重试。"
        return f"皮皮已生成 {tool_name} 的工具调用草案，等待执行。"

    def _has_card_ready_evidence(self, hits: list[RetrievalHit]) -> bool:
        return any(
            hit.get("score", 0.0) >= self.min_recommendation_score
            and bool(hit.get("payload", {}).get("has_verified_non_ai_image"))
            for hit in hits
        )

    def _success_message(self, tool_name: str) -> str:
        if tool_name == "create_recommendation_card":
            return "皮皮已通过工具生成推荐卡。"
        if tool_name == "create_help_card":
            return "皮皮已通过工具生成“求一个”。"
        if tool_name == "publish_help_card":
            return "皮皮已通过工具把“求一个”发出去了。"
        if tool_name == "record_human_evidence":
            return "皮皮已记录这句人类证据。"
        if tool_name == "finalize_recommendation":
            return "皮皮已通过工具生成最终推荐。"
        return "皮皮已完成工具调用。"


def get_deterministic_model_adapter() -> DeterministicPipiModelAdapter:
    """Factory kept explicit so tests can swap the adapter without global state."""

    return DeterministicPipiModelAdapter()
