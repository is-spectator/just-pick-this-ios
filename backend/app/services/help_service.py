from __future__ import annotations

from collections.abc import Mapping
from typing import Any


HUMAN_ONE_LINER_EVIDENCE_TYPE = "human_one_liner"
RAW_TEXT_ROLE = "human_evidence"


def human_one_liner_evidence(base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return metadata that keeps HelpAnswer text scoped to evidence."""

    metadata = dict(base or {})
    metadata.setdefault("evidence_type", HUMAN_ONE_LINER_EVIDENCE_TYPE)
    metadata.setdefault("raw_text_role", RAW_TEXT_ROLE)
    metadata.setdefault("human_evidence_only", True)
    return metadata


def help_answer_text(answer: Any) -> str:
    """Prefer normalized text, while treating raw_text only as human evidence."""

    return str(getattr(answer, "normalized_text", None) or getattr(answer, "raw_text", "") or "")


def is_finalization_ready(*, answer_count: int, min_answers_required: int) -> bool:
    return answer_count >= min_answers_required


__all__ = [
    "HUMAN_ONE_LINER_EVIDENCE_TYPE",
    "RAW_TEXT_ROLE",
    "help_answer_text",
    "human_one_liner_evidence",
    "is_finalization_ready",
]
