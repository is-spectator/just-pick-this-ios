from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any


HUMAN_ONE_LINER_EVIDENCE_TYPE = "human_one_liner"
RAW_TEXT_ROLE = "human_evidence"
_GENERIC_LOW_VALUE_ANSWERS = {
    "随便",
    "都行",
    "都可以",
    "不知道",
    "不知道啊",
    "不了解",
    "没去过",
    "没吃过",
    "好吃",
    "挺好",
    "不错",
    "可以",
    "还行",
    "推荐",
    "看看",
    "问别人",
}
_PUNCTUATION_RE = re.compile(r"[\s,，。.!！?？、;；:：\"'“”‘’（）()\[\]{}<>《》|/\\_-]+")
_REPEATED_CHAR_RE = re.compile(r"^(.)\1{3,}$")
_CONTACT_SPAM_RE = re.compile(
    r"(加我|联系我|私聊|vx[:：]?\w+|v信|微信号|qq[:：]?\w+|二维码|https?://|www\.)",
    re.IGNORECASE,
)
_ABUSE_TERMS = ("约炮", "裸聊")
_ILLEGAL_REQUEST_RE = re.compile(r"(买毒|贩毒|毒品|办假证|代开发票|偷拍视频|偷拍)")
_PRIVACY_HARM_RE = re.compile(r"(人肉|开盒|身份证号|手机号|家庭住址|住址)")


@dataclass(frozen=True)
class OneLinerQuality:
    accepted: bool
    normalized_key: str
    reason: str | None = None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class OneLinerAbuseCheck:
    unsafe: bool
    normalized_key: str
    reason: str | None = None
    issues: tuple[str, ...] = ()
    priority: int = 100


@dataclass(frozen=True)
class HelpCardAbuseCheck:
    unsafe: bool
    normalized_key: str
    reason: str | None = None
    issues: tuple[str, ...] = ()
    priority: int = 100


def human_one_liner_evidence(base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return metadata that keeps HelpAnswer text scoped to evidence."""

    metadata = dict(base or {})
    metadata.setdefault("evidence_type", HUMAN_ONE_LINER_EVIDENCE_TYPE)
    metadata.setdefault("raw_text_role", RAW_TEXT_ROLE)
    metadata.setdefault("human_evidence_only", True)
    return metadata


def normalize_one_liner_key(text: str) -> str:
    """Return a compact key for duplicate/low-effort answer checks."""

    compact = _PUNCTUATION_RE.sub("", str(text or "").strip().lower())
    return compact


def assess_one_liner_quality(text: str) -> OneLinerQuality:
    """Classify obvious low-value one-liners before they enter the reward queue.

    This is intentionally conservative: it blocks clear spam/generic answers,
    while leaving nuanced quality selection to the finalizer and human review.
    """

    normalized_key = normalize_one_liner_key(text)
    issues: list[str] = []
    if not normalized_key:
        issues.append("empty")
    if len(normalized_key) < 2:
        issues.append("too_short")
    if normalized_key in _GENERIC_LOW_VALUE_ANSWERS:
        issues.append("generic")
    if _REPEATED_CHAR_RE.match(normalized_key):
        issues.append("repeated_char")
    if normalized_key.isdigit():
        issues.append("numeric_only")
    if len(set(normalized_key)) <= 2 and len(normalized_key) >= 6:
        issues.append("low_entropy")

    accepted = not issues
    return OneLinerQuality(
        accepted=accepted,
        normalized_key=normalized_key,
        reason=issues[0] if issues else None,
        issues=tuple(issues),
    )


def detect_one_liner_abuse(text: str) -> OneLinerAbuseCheck:
    """Detect obvious unsafe or off-platform one-liners before reward handling.

    This intentionally avoids broad moderation. It only catches clear contact
    solicitation, external links, or adult-harassment terms so normal human
    evidence can continue to flow into finalization.
    """

    normalized_key = normalize_one_liner_key(text)
    issues: list[str] = []
    priority = 100
    if _CONTACT_SPAM_RE.search(str(text or "")):
        issues.append("contact_spam")
        priority = min(priority, 20)
    if any(term in normalized_key for term in _ABUSE_TERMS):
        issues.append("adult_harassment")
        priority = min(priority, 10)
    return OneLinerAbuseCheck(
        unsafe=bool(issues),
        normalized_key=normalized_key,
        reason=issues[0] if issues else None,
        issues=tuple(issues),
        priority=priority,
    )


def detect_help_card_abuse(
    *,
    title: str,
    context_text: str = "",
    payload: Mapping[str, Any] | None = None,
) -> HelpCardAbuseCheck:
    """Detect obvious unsafe help-card requests before they enter the public feed."""

    payload = payload or {}
    text_parts = [title, context_text]
    for key in ("context", "wants", "avoids", "constraints"):
        value = payload.get(key)
        if value:
            text_parts.append(str(value))
    text = " ".join(str(part or "") for part in text_parts)
    normalized_key = normalize_one_liner_key(text)
    issues: list[str] = []
    priority = 100
    if _CONTACT_SPAM_RE.search(text):
        issues.append("contact_spam")
        priority = min(priority, 20)
    if any(term in normalized_key for term in _ABUSE_TERMS):
        issues.append("adult_harassment")
        priority = min(priority, 10)
    if _ILLEGAL_REQUEST_RE.search(normalized_key):
        issues.append("illegal_request")
        priority = min(priority, 5)
    if _PRIVACY_HARM_RE.search(normalized_key):
        issues.append("privacy_harm")
        priority = min(priority, 15)
    return HelpCardAbuseCheck(
        unsafe=bool(issues),
        normalized_key=normalized_key,
        reason=issues[0] if issues else None,
        issues=tuple(issues),
        priority=priority,
    )


def one_liner_quality_metadata(quality: OneLinerQuality) -> dict[str, Any]:
    return {
        "accepted": quality.accepted,
        "normalized_key": quality.normalized_key,
        "reason": quality.reason,
        "issues": list(quality.issues),
    }


def help_answer_text(answer: Any) -> str:
    """Prefer normalized text, while treating raw_text only as human evidence."""

    return str(getattr(answer, "normalized_text", None) or getattr(answer, "raw_text", "") or "")


def is_finalization_ready(*, answer_count: int, min_answers_required: int) -> bool:
    return answer_count >= min_answers_required


__all__ = [
    "HUMAN_ONE_LINER_EVIDENCE_TYPE",
    "RAW_TEXT_ROLE",
    "OneLinerQuality",
    "OneLinerAbuseCheck",
    "HelpCardAbuseCheck",
    "assess_one_liner_quality",
    "detect_help_card_abuse",
    "detect_one_liner_abuse",
    "help_answer_text",
    "human_one_liner_evidence",
    "is_finalization_ready",
    "normalize_one_liner_key",
    "one_liner_quality_metadata",
]
