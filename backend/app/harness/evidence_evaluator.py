"""Evidence quality helpers shared by graph and PipiLoop routing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


GENERIC_DECISION_FACTOR_COMPACTS = {
    "稳",
    "很稳",
    "最稳",
    "靠谱",
    "不踩雷",
    "少踩雷",
    "不折腾",
    "适合现在直接决定",
    "适合现在直接做决定",
    "不用继续横向比较适合现在直接决定",
    "不用继续横向比较适合现在直接做决定",
    "这一个证据最稳",
    "先选这家",
}

DECISION_FACTOR_SPECIFIC_MARKERS = (
    "三里屯",
    "朝阳",
    "望京",
    "南锣",
    "四季民福",
    "海底捞",
    "喜晋道",
    "大同",
    "韩国",
    "明洞",
    "圣水",
    "热干面",
    "川菜",
    "粤菜",
    "烤鸭",
    "火锅",
    "番茄锅",
    "菌汤",
    "刀削面",
    "广东人",
    "清淡",
    "不辣",
    "不能吃辣",
    "两个人",
    "第一次",
    "带爸妈",
    "朋友",
    "预算",
    "小众",
    "步行",
    "分钟",
    "米",
    "公里",
    "距离",
    "路线",
    "附近",
    "招牌",
    "经典",
    "地方记忆点",
    "赶时间",
    "出餐",
)


def evaluate_retrieval_hits(hits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return whether retrieval evidence can safely create one recommendation card.

    AMap/POI candidates are useful place evidence, but not automatically answer
    evidence. They need an anchored decision factor that references the user's
    stated food/preference/route context.
    """

    missing: set[str] = set()
    best_confidence = 0.0
    has_any_hit = bool(hits)

    for hit in hits:
        score = _hit_score(hit)
        payload = _payload(hit)
        hit_missing = missing_requirements_for_hit(payload)
        if not hit_missing:
            best_confidence = max(best_confidence, score)
        else:
            missing.update(hit_missing)

    if best_confidence >= 0.7:
        return {
            "can_recommend": True,
            "confidence": round(best_confidence, 2),
            "missing_requirements": [],
            "reason": "Matched answer evidence with verified media or qualified place evidence.",
        }

    if not has_any_hit:
        missing.add("retrieval_hit")

    confidence = min(best_confidence, 0.69)
    if confidence == 0.0 and has_any_hit:
        confidence = min(max(_hit_score(hit) for hit in hits), 0.69)
    return {
        "can_recommend": False,
        "confidence": round(confidence, 2),
        "missing_requirements": sorted(missing or {"weak_intent_match"}),
        "reason": "Not enough evidence.",
    }


def is_card_ready_hit(hit: Mapping[str, Any]) -> bool:
    if _hit_score(hit) < 0.7:
        return False
    return not missing_requirements_for_hit(_payload(hit))


def missing_requirements_for_hit(payload: Mapping[str, Any]) -> set[str]:
    missing: set[str] = set()
    has_answer = _has_answer_evidence(payload)
    has_place = _has_place_evidence(payload)
    has_image = _has_verified_non_ai_image(payload)
    has_qualified_place = has_place and _has_qualified_place_decision(payload)

    if not has_answer:
        missing.add("answer_evidence")
    if has_place and not has_qualified_place:
        missing.add("taste_or_preference_evidence")
    if not has_image and not has_qualified_place:
        missing.add("verified_non_ai_image")
    if payload.get("human_help_required"):
        missing.add("human_help_required")
    return missing


def evidence_layers_for_payload(payload: Mapping[str, Any]) -> list[str]:
    layers = _string_list(payload.get("evidence_layers"))
    if payload.get("intent_answer_id") or payload.get("reference_intent_answer_id"):
        layers.append("intent_answer")
    if payload.get("has_answer_evidence"):
        layers.append("answer_evidence")
    if payload.get("help_answer_id"):
        layers.append("human_answer")
    if payload.get("web_reference"):
        layers.append("web_result")
    if payload.get("has_place_evidence") or payload.get("place"):
        layers.append("amap_poi")
    if payload.get("route"):
        layers.append("route")
    if payload.get("has_verified_non_ai_image") or payload.get("image_asset_id"):
        layers.append("image_asset")
    if payload.get("decision_factor"):
        layers.append("decision_factor")
    return list(dict.fromkeys(layers))


def is_generic_decision_factor(text: str) -> bool:
    compact = _compact_text(text)
    if not compact:
        return True
    if compact in GENERIC_DECISION_FACTOR_COMPACTS:
        return True
    if len(compact) <= 6 and any(term in compact for term in ("稳", "靠谱", "不踩雷")):
        return True
    if "适合现在直接" in text and not any(
        marker in text for marker in DECISION_FACTOR_SPECIFIC_MARKERS
    ):
        return True
    return not any(marker in text for marker in DECISION_FACTOR_SPECIFIC_MARKERS)


def _has_answer_evidence(payload: Mapping[str, Any]) -> bool:
    if payload.get("intent_answer_id"):
        return True
    if payload.get("has_answer_evidence"):
        return True
    return bool(set(evidence_layers_for_payload(payload)) & {"intent_answer", "answer_evidence"})


def _has_place_evidence(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("has_place_evidence") and payload.get("place") and payload.get("action"))


def _has_qualified_place_decision(payload: Mapping[str, Any]) -> bool:
    if not _has_place_evidence(payload):
        return False
    decision_text = str(payload.get("decision_factor") or "").strip()
    if is_generic_decision_factor(decision_text):
        return False
    layers = set(evidence_layers_for_payload(payload))
    if layers & {"route", "decision_factor", "answer_evidence", "intent_answer"}:
        return True
    return bool(payload.get("has_taste_or_preference_evidence"))


def _has_verified_non_ai_image(payload: Mapping[str, Any]) -> bool:
    if payload.get("has_verified_non_ai_image") and payload.get("image_asset_id"):
        return True
    image_asset = payload.get("image_asset")
    if not isinstance(image_asset, Mapping):
        return False
    verified = bool(image_asset.get("verified") or image_asset.get("is_verified"))
    is_ai_generated = bool(image_asset.get("is_ai_generated"))
    return verified and not is_ai_generated and bool(
        image_asset.get("id") or payload.get("image_asset_id")
    )


def _hit_score(hit: Mapping[str, Any]) -> float:
    try:
        return float(hit.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _payload(hit: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = hit.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _compact_text(value: str) -> str:
    removals = " \t\r\n,.;:!?，。；：！？、（）()【】[]《》\"'`"
    compact = value.casefold()
    for char in removals:
        compact = compact.replace(char, "")
    return compact
