from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


LocationState = Literal["in_area", "in_venue", "unknown"]


class QueryRewriteResult(BaseModel):
    original_query: str
    canonical_query: str
    extracted_slots: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


_CITY_ALIASES: tuple[tuple[str, str], ...] = (
    ("北京市", "北京"),
    ("北京", "北京"),
    ("上海市", "上海"),
    ("上海", "上海"),
    ("广州市", "广州"),
    ("广州", "广州"),
    ("深圳市", "深圳"),
    ("深圳", "深圳"),
    ("成都", "成都"),
    ("首尔", "首尔"),
    ("韩国", "韩国"),
    ("京都", "京都"),
    ("曼谷", "曼谷"),
)

_AREA_ALIASES: tuple[tuple[str, str], ...] = (
    ("望京SOHO", "望京 SOHO"),
    ("望京soho", "望京 SOHO"),
    ("望京", "望京"),
    ("朝阳SOHO", "朝阳SOHO"),
    ("朝阳soho", "朝阳SOHO"),
    ("朝阳区", "朝阳区"),
    ("三里屯", "三里屯"),
    ("南锣鼓巷", "南锣鼓巷"),
    ("王府井", "王府井"),
    ("故宫", "故宫"),
    ("前门", "前门"),
    ("国贸", "国贸"),
    ("五道口", "五道口"),
    ("簋街", "簋街"),
    ("西单", "西单"),
    ("后海", "后海"),
    ("南京西路", "南京西路"),
    ("徐家汇", "徐家汇"),
    ("静安寺", "静安寺"),
    ("陆家嘴", "陆家嘴"),
    ("互联宝地", "互联宝地"),
    ("春熙路", "春熙路"),
    ("太古里", "太古里"),
    ("宽窄巷子", "宽窄巷子"),
    ("牛街", "牛街"),
    ("天河", "天河"),
    ("南山", "南山"),
)

_VENUE_ALIASES: tuple[tuple[str, str], ...] = (
    ("海底捞火锅", "海底捞"),
    ("海底捞", "海底捞"),
    ("haidilao", "海底捞"),
    ("Haidilao", "海底捞"),
    ("四季民福故宫店", "四季民福"),
    ("四季民福故宫", "四季民福"),
    ("故宫四季民福", "四季民福"),
    ("四季民福烤鸭店", "四季民福"),
    ("四季民福烤鸭", "四季民福"),
    ("四季民福", "四季民福"),
    ("西贝", "西贝"),
    ("陶陶居", "陶陶居"),
    ("喜晋道", "喜晋道"),
    ("麦当劳", "麦当劳"),
    ("聚宝源", "聚宝源"),
    ("大董", "大董"),
    ("点都德", "点都德"),
)

_FOOD_ITEMS = ("热干面", "烤鸭", "甜品", "咖啡", "小吃", "酸汤", "咖喱饭")
_CUISINES = ("川菜", "粤菜", "火锅", "北京菜", "韩餐", "韩国菜", "日料", "日本菜", "贵州菜", "客家菜", "朝鲜族菜", "素食")


def rewrite_query(message: str) -> QueryRewriteResult:
    original = str(message or "").strip()
    compact = _compact(original)
    slots: dict[str, Any] = {}
    notes: list[str] = []

    city = _first_alias(compact, _CITY_ALIASES)
    area = _first_alias(compact, _AREA_ALIASES)
    venue = _first_alias(compact, _VENUE_ALIASES)
    food_item = _first_term(compact, _FOOD_ITEMS)
    cuisine = _first_term(compact, _CUISINES)

    if city:
        slots["city"] = city
    if area:
        slots["area"] = area
    if venue:
        slots["venue"] = venue
    if food_item:
        slots["food_item"] = food_item
    if cuisine:
        slots["cuisine"] = _normalize_cuisine(cuisine)

    party_size = _party_size(compact)
    if party_size is not None:
        slots["party_size"] = party_size

    spice_preference = _spice_preference(compact)
    if spice_preference:
        slots["spice_preference"] = spice_preference

    taste_preference = _taste_preference(compact)
    if taste_preference:
        slots["taste_preference"] = taste_preference

    budget_preference = _budget_preference(compact)
    if budget_preference:
        slots["budget_preference"] = budget_preference

    user_profile = _user_profile(compact)
    if user_profile:
        slots["user_profile"] = user_profile
        if "guangdong" in user_profile and "light" not in taste_preference:
            slots["taste_preference"] = [*taste_preference, "light"]
            notes.append("Guangdong profile implies a light/cantonese-friendly preference.")
        if "guangdong" in user_profile and not slots.get("cuisine"):
            slots["cuisine"] = "粤菜"
            notes.append("Guangdong profile implies Cantonese cuisine should be considered.")

    task = _task(compact)
    if task:
        slots["task"] = task

    location_state: LocationState = "unknown"
    if venue:
        location_state = "in_venue"
    elif area:
        location_state = "in_area"
    slots["location_state"] = location_state

    canonical = _canonical_query(original, slots)
    confidence = _confidence(slots)
    return QueryRewriteResult(
        original_query=original,
        canonical_query=canonical,
        extracted_slots=slots,
        confidence=confidence,
        notes=notes,
    )


def _compact(value: str) -> str:
    return "".join(value.strip().split())


def _first_alias(message: str, aliases: tuple[tuple[str, str], ...]) -> str | None:
    lower = message.lower()
    for raw, canonical in aliases:
        if raw.lower() in lower:
            return canonical
    return None


def _first_term(message: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        if term in message:
            return term
    return None


def _normalize_cuisine(value: str) -> str:
    return {
        "韩国菜": "韩餐",
        "日本菜": "日料",
    }.get(value, value)


def _party_size(message: str) -> int | None:
    if any(term in message for term in ("两个人", "2个人", "俩人", "两人", "2人")):
        return 2
    if any(term in message for term in ("一个人", "1个人", "单人", "一人")):
        return 1
    if any(term in message for term in ("带爸妈", "带父母", "家庭", "家人")):
        return 3
    if "朋友局" in message or "朋友" in message:
        return 4
    return None


def _spice_preference(message: str) -> str | None:
    if any(term in message for term in ("不太能吃辣", "不能吃辣", "不吃辣", "不辣", "少辣")):
        return "not_spicy"
    if any(term in message for term in ("想吃辣", "辣一点", "能吃辣")):
        return "spicy"
    return None


def _taste_preference(message: str) -> list[str]:
    values: list[str] = []
    if any(term in message for term in ("清淡", "清爽", "淡一点", "别太油")):
        values.append("light")
    if "粤菜" in message:
        values.append("cantonese")
    return values


def _budget_preference(message: str) -> str | None:
    if any(term in message for term in ("预算别太高", "预算不高", "不贵", "便宜", "别太夸张")):
        return "moderate"
    return None


def _user_profile(message: str) -> list[str]:
    values: list[str] = []
    if any(term in message for term in ("广东人", "广州人", "深圳人")):
        values.append("guangdong")
    return values


def _task(message: str) -> str | None:
    if any(term in message for term in ("帮我点", "点菜", "怎么点", "点什么", "点啥")):
        return "order_dishes"
    if any(term in message for term in ("帮我找", "有什么好吃", "有啥好吃", "选一家", "推荐个餐厅", "吃什么", "吃啥")):
        return "choose_restaurant"
    return None


def _canonical_query(original: str, slots: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("city", "area", "venue", "food_item", "cuisine", "task"):
        value = slots.get(key)
        if value:
            parts.append(str(value))
    if slots.get("spice_preference"):
        parts.append(str(slots["spice_preference"]))
    if slots.get("taste_preference"):
        parts.extend(str(item) for item in slots["taste_preference"])
    if slots.get("party_size"):
        parts.append(f"{slots['party_size']}人")
    return " ".join(parts) if parts else original


def _confidence(slots: dict[str, Any]) -> float:
    score = 0.45
    for key in ("city", "area", "venue", "food_item", "cuisine", "task"):
        if slots.get(key):
            score += 0.08
    if slots.get("party_size"):
        score += 0.04
    if slots.get("taste_preference") or slots.get("spice_preference"):
        score += 0.04
    return min(score, 0.95)


__all__ = ["QueryRewriteResult", "rewrite_query"]
