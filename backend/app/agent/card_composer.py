"""Card copy composition for Pipi recommendation cards.

Database answers are treated as trusted references, not final user-facing copy.
This module adapts retrieved evidence to the current user message while leaving
card creation, image binding, and persistence to tools/services.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.models import ImageAsset, IntentAnswer


class CardDraft(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    subtitle: str = Field(min_length=1, max_length=140)
    reason: str = Field(min_length=1, max_length=360)
    bullets: list[str] = Field(min_length=2, max_length=4)
    warning: str | None = Field(default=None, max_length=160)
    followups: list[str] = Field(default_factory=list, max_length=4)
    confidence: float = Field(ge=0.0, le=1.0)
    model_provider: str = "deterministic"
    model_name: str = "deterministic-v0"
    used_web_search: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bullets", "followups")
    @classmethod
    def clean_lines(cls, lines: list[str]) -> list[str]:
        cleaned = [line.strip() for line in lines if line and line.strip()]
        if len(cleaned) != len(set(cleaned)):
            deduped: list[str] = []
            for line in cleaned:
                if line not in deduped:
                    deduped.append(line)
            cleaned = deduped
        return cleaned


def compose_card_draft(
    *,
    user_message: str,
    primary_hit: dict[str, Any],
    all_hits: list[dict[str, Any]],
    intent_answer: IntentAnswer | None,
    image_asset: ImageAsset,
) -> CardDraft:
    """Compose a user-facing Top 1 card from retrieved reference evidence."""

    settings = get_settings()
    reference = _reference_snapshot(
        user_message=user_message,
        primary_hit=primary_hit,
        all_hits=all_hits,
        intent_answer=intent_answer,
        image_asset=image_asset,
    )
    web_hits = _web_search(user_message) if settings.web_search_provider != "disabled" else []

    if settings.pipi_card_composer == "deepseek" and settings.deepseek_api_key is not None:
        try:
            return _compose_with_deepseek(reference=reference, web_hits=web_hits)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            draft = _compose_deterministically(reference=reference, web_hits=web_hits)
            draft.metadata["composer_fallback_reason"] = str(exc)
            return draft

    return _compose_deterministically(reference=reference, web_hits=web_hits)


def _reference_snapshot(
    *,
    user_message: str,
    primary_hit: dict[str, Any],
    all_hits: list[dict[str, Any]],
    intent_answer: IntentAnswer | None,
    image_asset: ImageAsset,
) -> dict[str, Any]:
    payload = dict(primary_hit.get("payload") or {})
    return {
        "user_message": user_message,
        "primary_hit": {
            "title": primary_hit.get("title"),
            "score": primary_hit.get("score"),
            "payload": payload,
        },
        "all_hits": [
            {
                "title": hit.get("title"),
                "score": hit.get("score"),
                "payload": hit.get("payload", {}),
            }
            for hit in all_hits
        ],
        "reference_answer": {
            "id": str(intent_answer.id) if intent_answer else None,
            "text": intent_answer.answer_text if intent_answer else payload.get("reference_answer"),
            "tags": intent_answer.tags_json if intent_answer else [],
            "evidence": intent_answer.evidence_json if intent_answer else {},
        },
        "image_asset": {
            "id": str(image_asset.id),
            "place_key": image_asset.place_key,
            "item_key": image_asset.item_key,
            "verified": image_asset.verified and image_asset.verification_status == "verified",
            "is_ai_generated": image_asset.is_ai_generated,
        },
    }


def _compose_deterministically(reference: dict[str, Any], web_hits: list[dict[str, str]]) -> CardDraft:
    message = reference["user_message"]
    image = reference["image_asset"]
    place_key = image.get("place_key") or ""
    score = float(reference["primary_hit"].get("score") or 0.82)

    if place_key == "korea-seongsu":
        normalized_message = message.lower()
        wants_not_myeongdong = "明洞" in message or "myeongdong" in normalized_message
        wants_niche = any(
            token in normalized_message
            for token in ("小众", "买手", "品牌", "咖啡", "shopping", "brand", "coffee")
        )
        title = "去圣水"
        subtitle = (
            "别去明洞当背景板了，这次去圣水更适合你。"
            if wants_not_myeongdong
            else "这次直接去圣水，逛店、咖啡和顺手买东西都更顺。"
        )
        reason_parts = ["它比明洞更生活方式"]
        if wants_niche:
            reason_parts.append("小众品牌、咖啡店和生活方式店更集中")
        else:
            reason_parts.append("逛起来比做攻略更省心")
        reason = "，".join(reason_parts) + "。"
        bullets = [
            "贴合你“不想去明洞”的限制" if wants_not_myeongdong else "适合直接逛，不用做复杂攻略",
            "小店、咖啡和生活方式品牌密度高",
            "路线容错高，到了附近顺着街区走就行",
        ]
        warning = "如果你只想买免税店或游客爆款，明洞会更直接。"
        followups = ["为什么是圣水?", "有没有更安静的街区?"]
    elif place_key == "datong-xijindao":
        title = "喜晋道 · 刀削面加肉丸子"
        subtitle = "在大同喜晋道别纠结，先点这个组合。"
        reason = "数据库参考答案指向刀削面，但皮皮按你“到店不知道吃什么”的场景，把它收敛成更稳的点单组合。"
        bullets = ["刀削面是店里的低后悔主线", "肉丸子补足香气和满足感", "第一次到店不用比较菜单"]
        warning = "不想吃面或想吃清淡的，就别选这个。"
        followups = ["为什么这样点?", "能不能换清淡点?"]
    else:
        fallback_title = reference["primary_hit"].get("title") or "就选这个"
        title = str(fallback_title)[:40]
        subtitle = "皮皮按数据库参考和你这句话，先收敛成一个低后悔选择。"
        reason = str(reference["reference_answer"].get("text") or "已有参考答案，但还需要结合当前问题表达。")
        bullets = ["使用数据库参考作为证据", "只输出一个选择", "图片仍来自 verified 非 AI 资产"]
        warning = "如果你的偏好和这条参考相反，就别选。"
        followups = ["为什么选这个?", "有没有别的选择?"]

    if web_hits:
        bullets = [*bullets[:2], "已参考实时网页摘要，但没有让网页绕过数据库图片约束"]

    return CardDraft(
        title=title,
        subtitle=subtitle,
        reason=reason,
        bullets=bullets,
        warning=warning,
        followups=followups,
        confidence=max(0.7, min(score, 0.94)),
        used_web_search=bool(web_hits),
        metadata={
            "composition": "reference_answer_adapted",
            "reference_answer_id": reference["reference_answer"].get("id"),
        },
    )


def _compose_with_deepseek(*, reference: dict[str, Any], web_hits: list[dict[str, str]]) -> CardDraft:
    settings = get_settings()
    if settings.deepseek_api_key is None:
        raise ValueError("DEEPSEEK_API_KEY is required")

    prompt = {
        "reference": reference,
        "web_hits": web_hits,
        "rules": [
            "数据库答案只是可信参考，不是最终文案，不要照抄 reference_answer.text。",
            "只能推荐一个 Top 1。",
            "不要编造图片 URL；图片由 image_asset.id 绑定。",
            "如果证据不足，应降低 confidence，但不要在这里创建求助卡。",
            "输出中文 JSON，字段为 title/subtitle/reason/bullets/warning/followups/confidence。",
        ],
    }
    response = httpx.post(
        f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        },
        timeout=settings.deepseek_timeout_seconds,
        json={
            "model": settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是“就选这个”的 AI 管家皮皮。"
                        "你把检索证据加工成当下用户可直接采用的一张 Top 1 推荐卡。"
                        "数据库答案是参考证据，不是最终答案。只输出 JSON。"
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    data = _extract_json_object(content)
    draft = CardDraft.model_validate(data)
    return draft.model_copy(
        update={
            "model_provider": "deepseek",
            "model_name": settings.deepseek_model,
            "used_web_search": bool(web_hits),
            "metadata": {
                **draft.metadata,
                "composition": "deepseek_reference_adapted",
                "reference_answer_id": reference["reference_answer"].get("id"),
            },
        }
    )


def _web_search(query: str) -> list[dict[str, str]]:
    settings = get_settings()
    if settings.web_search_provider != "tavily" or settings.tavily_api_key is None:
        return []

    response = httpx.post(
        "https://api.tavily.com/search",
        timeout=settings.web_search_timeout_seconds,
        json={
            "api_key": settings.tavily_api_key.get_secret_value(),
            "query": query,
            "max_results": 3,
            "search_depth": "basic",
        },
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "content": str(item.get("content") or "")[:500],
        }
        for item in results[:3]
        if item.get("url")
    ]


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("DeepSeek response did not contain a JSON object")
