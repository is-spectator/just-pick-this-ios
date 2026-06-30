from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.schemas.chat import ResponseKind
from app.services.intent_router import (
    ClarificationDecision,
    detect_app_help,
    detect_chitchat,
    detect_clarification_needed,
)


_CARDS: dict[str, dict[str, Any]] = {}
_HELP_CARDS: dict[str, dict[str, Any]] = {}


FORBIDDEN_TERMS = ("Top 3", "榜单", "你可以考虑", "以下是几个", "推荐几个")
SIJIMINFU_ALIASES = (
    "四季民福",
    "四季民福故宫",
    "四季民福故宫店",
    "故宫四季民福",
    "四季民福烤鸭",
    "四季民福烤鸭店",
)
HAIDILAO_ALIASES = (
    "海底捞",
    "海底捞火锅",
    "haidilao",
)
KNOWN_AREAS = ("三里屯",)
OTHER_VENUE_ALIASES: dict[str, tuple[str, ...]] = {
    "西贝": ("西贝", "西贝莜面村"),
    "陶陶居": ("陶陶居",),
    "喜晋道": ("喜晋道",),
    "聚宝源": ("聚宝源",),
    "大董": ("大董", "大董烤鸭"),
    "麦当劳": ("麦当劳", "mcdonald", "mcdonalds"),
    "点都德": ("点都德",),
}
ORDERING_TERMS = (
    "帮我点",
    "帮我点菜",
    "帮我搭",
    "帮我搭配",
    "帮我选",
    "帮我选一套",
    "帮我看看",
    "点菜",
    "点一下菜",
    "点什么",
    "点几个",
    "点一套",
    "点一下",
    "点单",
    "想点",
    "值得点",
    "怎么点",
    "吃什么",
    "哪个菜",
    "你决定",
    "你帮我决定",
    "直接决定",
    "替我点",
    "你点",
    "别浪费",
    "不要浪费",
    "别点太多",
    "清淡点",
    "清淡一点",
    "清爽点",
    "舒服点",
    "不腻",
    "第一次来",
    "第一次吃",
    "必点",
    "搭配",
    "配菜",
    "家庭",
    "一家人",
    "带家人",
    "朋友",
    "朋友局",
    "快点",
    "快速",
    "快到号",
    "到号",
    "到店了",
    "已经到了",
    "已经坐在",
    "坐在",
    "排到我了",
    "到了",
    "我到",
    "烤鸭",
    "菜单",
    "锅底",
    "番茄锅",
    "不辣",
    "太辣",
    "少辣",
    "稳妥",
    "组合",
    "两个人",
    "两人",
    "二个人",
    "2个人",
    "两人餐",
    "不太能吃辣",
    "不吃辣",
    "预算",
    "别太夸张",
    "别太高",
    "不贵",
    "招牌",
)
PRODUCT_ROUTES = (
    ("树莓派", "5 英寸 HDMI 小屏", "树莓派 · 桌搭小屏", "树莓派小屏先选 5 英寸 HDMI 款，供电和安装都更稳。"),
    ("咖啡手冲壶", "细嘴温控手冲壶", "咖啡 · 新手", "新手手冲先选温控和细嘴，控水比造型更影响成功率。"),
    ("手冲咖啡壶", "细嘴温控手冲壶", "咖啡 · 新手", "新手手冲先选温控和细嘴，控水比造型更影响成功率。"),
)


def should_use_smoke_runtime(payload: dict[str, Any]) -> bool:
    if not get_settings().allow_eval_bypass:
        return False
    if not _has_explicit_eval_bypass_opt_in(payload):
        return False
    client_context = payload.get("client_context") or {}
    device_uid = str(payload.get("device_id") or payload.get("device_uid") or "")
    source = str(client_context.get("source") or "")
    mode = str(client_context.get("mode") or "")
    if source == "pipi-eval-lab" or device_uid.startswith("eval-"):
        return False
    return source == "manual" and mode == "remote_smoke"


def _has_explicit_eval_bypass_opt_in(payload: dict[str, Any]) -> bool:
    client_context = payload.get("client_context") or {}
    metadata = payload.get("metadata") or {}
    headers = metadata.get("headers") if isinstance(metadata.get("headers"), dict) else {}
    return any(
        _truthy_flag(value)
        for value in (
            client_context.get("pipi_eval_mode"),
            client_context.get("x_pipi_eval_mode"),
            metadata.get("pipi_eval_mode"),
            headers.get("x-pipi-eval-mode"),
            headers.get("X-Pipi-Eval-Mode"),
        )
    )


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def run_smoke_chat_turn(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload["message"]).strip()
    conversation_id = payload.get("conversation_id") or str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    metadata = payload.get("metadata") or {}
    include_debug = bool((payload.get("client_context") or {}).get("include_debug"))

    if _is_publish_request(message):
        help_card = _published_help_card(metadata.get("help_card_id"))
        return _publish_help_response(
            conversation_id=conversation_id,
            turn_id=turn_id,
            include_debug=include_debug,
            help_card=help_card,
        )

    chitchat = detect_chitchat(message)
    if chitchat is not None:
        return _chitchat_response(
            conversation_id=conversation_id,
            turn_id=turn_id,
            include_debug=include_debug,
            assistant_message=chitchat.assistant_message,
            intent_key=chitchat.intent_key,
        )
    app_help = detect_app_help(message)
    if app_help is not None:
        return _chitchat_response(
            conversation_id=conversation_id,
            turn_id=turn_id,
            include_debug=include_debug,
            assistant_message=app_help.assistant_message,
            intent_key=app_help.intent_key,
        )

    resolved = _resolve_location_intent(message)

    if resolved["route"] == "venue_ordering":
        card = _venue_ordering_card(resolved["venue"])
        if card is not None:
            _CARDS[card["id"]] = card
            return _recommendation_response(
                conversation_id=conversation_id,
                turn_id=turn_id,
                include_debug=include_debug,
                assistant_message="就选这个。",
                location_state="in_venue",
                card=card,
                source_answer_type="ordering_bundle_answer",
            )

        help_card = _venue_help_card(message, venue=resolved["venue"], area=resolved["area"])
        _HELP_CARDS[help_card["id"]] = help_card
        return _help_response(
            conversation_id=conversation_id,
            turn_id=turn_id,
            include_debug=include_debug,
            help_card=help_card,
        )

    if _is_sanlitun_sichuan(message):
        card = _restaurant_card()
        _CARDS[card["id"]] = card
        return _recommendation_response(
            conversation_id=conversation_id,
            turn_id=turn_id,
            include_debug=include_debug,
            assistant_message="就选这个。",
            location_state="in_area",
            card=card,
            source_answer_type="area_intent_answer",
        )

    product_card = _product_card(message)
    if product_card is not None:
        _CARDS[product_card["id"]] = product_card
        return _recommendation_response(
            conversation_id=conversation_id,
            turn_id=turn_id,
            include_debug=include_debug,
            assistant_message="就选这个。",
            location_state="unknown",
            card=product_card,
            source_answer_type="product_intent_answer",
        )

    if not _has_enough_help_context(message):
        clarification = detect_clarification_needed(message)
        if clarification is not None:
            return _clarification_response(
                conversation_id=conversation_id,
                turn_id=turn_id,
                include_debug=include_debug,
                decision=clarification,
            )

    help_card = _venue_help_card(message) if _has_unknown_venue_context(message) else _area_help_card(message)
    _HELP_CARDS[help_card["id"]] = help_card
    return _help_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        include_debug=include_debug,
        help_card=help_card,
    )


def _chitchat_response(
    *,
    conversation_id: str,
    turn_id: str,
    include_debug: bool,
    assistant_message: str,
    intent_key: str,
) -> dict[str, Any]:
    return _chat_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_kind=ResponseKind.CHITCHAT,
        assistant_message=assistant_message,
        location_state="unknown",
        ui_events=[],
        data={},
        debug=_debug(
            enabled=include_debug,
            selected_tool=None,
            location_state="unknown",
            source_answer_type=None,
            intent_key=intent_key,
        ),
    )


def _clarification_response(
    *,
    conversation_id: str,
    turn_id: str,
    include_debug: bool,
    decision: ClarificationDecision,
) -> dict[str, Any]:
    return _chat_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_kind=ResponseKind.CLARIFICATION,
        assistant_message=decision.assistant_message,
        location_state=decision.location_state,
        ui_events=[],
        data={
            "clarification": {
                "missing_slots": decision.missing_slots,
                "question": decision.question,
            }
        },
        debug=_debug(
            enabled=include_debug,
            selected_tool=None,
            location_state=decision.location_state,
            source_answer_type=None,
            intent_key=decision.intent_key,
        ),
    )


def _recommendation_response(
    *,
    conversation_id: str,
    turn_id: str,
    include_debug: bool,
    assistant_message: str,
    location_state: str,
    card: dict[str, Any],
    source_answer_type: str,
) -> dict[str, Any]:
    return _chat_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_kind=ResponseKind.RECOMMENDATION_CARD,
        assistant_message=assistant_message,
        location_state=location_state,
        ui_events=[{"type": "show_recommendation_card", "card_id": card["id"]}],
        data={"recommendation_card": card},
        debug=_debug(
            enabled=include_debug,
            selected_tool="create_recommendation_card",
            location_state=location_state,
            source_answer_type=source_answer_type,
            card_id=card["id"],
        ),
        cards=[card],
    )


def _help_response(
    *,
    conversation_id: str,
    turn_id: str,
    include_debug: bool,
    help_card: dict[str, Any],
) -> dict[str, Any]:
    return _chat_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_kind=ResponseKind.HELP_CARD_DRAFT,
        assistant_message="这题先求一个。",
        location_state=help_card["location_state"],
        ui_events=[{"type": "show_help_card_draft", "help_card_id": help_card["id"]}],
        data={"help_card": help_card},
        debug=_debug(
            enabled=include_debug,
            selected_tool="draft_help_card",
            location_state=help_card["location_state"],
            source_answer_type=None,
            help_card_id=help_card["id"],
        ),
        help_cards=[help_card],
    )


def _publish_help_response(
    *,
    conversation_id: str,
    turn_id: str,
    include_debug: bool,
    help_card: dict[str, Any],
) -> dict[str, Any]:
    return _chat_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_kind=ResponseKind.HELP_CARD_DRAFT,
        assistant_message="已经发出去了。",
        location_state=help_card["location_state"],
        ui_events=[{"type": "help_card_published", "help_card_id": help_card["id"]}],
        data={"help_card": help_card},
        debug=_debug(
            enabled=include_debug,
            selected_tool="publish_help_card",
            location_state=help_card["location_state"],
            source_answer_type=None,
            help_card_id=help_card["id"],
        ),
        help_cards=[help_card],
    )


def get_smoke_card(card_id: str) -> dict[str, Any] | None:
    card = _CARDS.get(card_id)
    if card is None:
        return None
    return {"card": card, **card}


def get_smoke_help_card(help_card_id: str) -> dict[str, Any] | None:
    help_card = _HELP_CARDS.get(help_card_id)
    if help_card is None:
        return None
    return {"help_card": help_card, **help_card}


def assert_no_forbidden_terms(card: dict[str, Any]) -> None:
    text = str(card)
    for term in FORBIDDEN_TERMS:
        if term in text:
            raise HTTPException(status_code=500, detail=f"forbidden_term:{term}")


def _is_sanlitun_sichuan(message: str) -> bool:
    return "三里屯" in message and ("川菜" in message or "吃" in message)


def _is_sijiminfu_ordering(message: str) -> bool:
    return _detect_known_venue(message) == "四季民福" and _has_ordering_language(message)


def _is_unknown_venue_ordering(message: str) -> bool:
    return _has_unknown_venue_context(message) and _has_ordering_language(message)


def _is_publish_request(message: str) -> bool:
    return any(term in message for term in ("发出去", "发布", "发个求助", "投出去"))


def _published_help_card(help_card_id: Any) -> dict[str, Any]:
    help_card: dict[str, Any] | None = None
    if help_card_id:
        help_card = _HELP_CARDS.get(str(help_card_id).lower()) or _HELP_CARDS.get(str(help_card_id))
    if help_card is None:
        help_card = _help_card(
            "发出去",
            title="这题求懂的人来一句",
            location_state="unknown",
            context={"task": "publish_help_card", "source": "ios"},
        )
        _HELP_CARDS[help_card["id"]] = help_card
    help_card["status"] = "published"
    return help_card


def _has_enough_help_context(message: str) -> bool:
    return _has_unknown_venue_context(message) or _has_specific_unknown_area_food_context(message)


def _has_unknown_venue_context(message: str) -> bool:
    return any(
        cue in message
        for cue in (
            "你没听过",
            "没听过",
            "没有线上菜单",
            "刚开的店",
            "网上应该没资料",
            "店招",
            "店名不清楚",
            "菜单很多",
            "看不懂",
            "没写价格",
            "没有评价",
            "没看到评价",
            "小店",
            "小馆",
            "小馆子",
            "小面馆",
            "面馆",
            "本地烧烤小店",
            "路边小摊",
            "饺子铺",
            "食堂窗口",
            "手写菜单",
            "私房菜",
            "藏在楼里",
            "老板问我要什么",
        )
    )


def _has_specific_unknown_area_food_context(message: str) -> bool:
    return _has_uncertain_location_context(message) and _has_specific_food_term(message)


def _has_uncertain_location_context(message: str) -> bool:
    return any(
        cue in message
        for cue in (
            "很偏",
            "说不清楚的位置",
            "郊区",
            "小路",
            "公园边",
            "定位不准",
            "新开发区",
            "仓储",
            "外环",
            "不知道具体地址",
            "只知道在北京",
            "工业区",
            "城郊",
            "村口",
            "小站",
            "无名",
            "北边很远",
            "不熟的地方",
        )
    )


def _has_specific_food_term(message: str) -> bool:
    return any(
        food in message
        for food in (
            "贵州菜",
            "客家菜",
            "朝鲜族菜",
            "藏餐",
            "素食",
            "贵州酸汤",
            "湖北菜",
            "兰州小吃",
            "海鲜",
            "延边菜",
            "咖喱饭",
            "火锅",
            "烧烤",
            "饺子",
            "喝点汤",
            "汤",
        )
    )


def _resolve_location_intent(message: str) -> dict[str, str | None]:
    venue = _detect_known_venue(message)
    area = _detect_area(message)
    if venue and _has_ordering_language(message):
        return {"route": "venue_ordering", "venue": venue, "area": area}
    if venue:
        return {"route": "venue", "venue": venue, "area": area}
    if area:
        return {"route": "area", "venue": None, "area": area}
    return {"route": "unknown", "venue": None, "area": None}


def _detect_known_venue(message: str) -> str | None:
    normalized = message.lower()
    if any(alias.lower() in normalized for alias in HAIDILAO_ALIASES):
        return "海底捞"
    if any(alias in message for alias in SIJIMINFU_ALIASES):
        return "四季民福"
    for venue, aliases in OTHER_VENUE_ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            return venue
    return None


def _detect_area(message: str) -> str | None:
    return next((area for area in KNOWN_AREAS if area in message), None)


def _has_ordering_language(message: str) -> bool:
    return any(term in message for term in ORDERING_TERMS)


def _restaurant_card() -> dict[str, Any]:
    card = {
        "id": str(uuid.uuid4()),
        "type": "recommendation_card",
        "version": "onsite_food_beijing_v1",
        "target_type": "restaurant",
        "title": "三里屯川菜馆候选",
        "subtitle": "三里屯 · 川菜",
        "decision_factor": {
            "key": "nearby_sichuan_stable",
            "text": "三里屯附近想吃川菜，先选距离和口味容错率最稳的。",
        },
        "image": None,
        "provenance": {
            "source_answer_id": "seed_area_sanlitun_sichuan",
            "source_answer_type": "area_intent_answer",
            "evidence_ids": ["seed_source_sanlitun_sichuan"],
            "retrieval_run_id": "seed_retrieval",
        },
        "ui": {"layout": "minimal_recommendation", "show_actions": False},
    }
    assert_no_forbidden_terms(card)
    return card


def _ordering_bundle_card() -> dict[str, Any]:
    card = {
        "id": str(uuid.uuid4()),
        "type": "recommendation_card",
        "version": "onsite_food_beijing_v1",
        "target_type": "ordering_bundle",
        "title": "烤鸭 + 清爽配菜 + 甜品",
        "subtitle": "四季民福故宫店 · 默认 2 人",
        "decision_factor": {
            "key": "signature_first",
            "text": "第一次来四季民福，先吃招牌，口味最稳。",
        },
        "image": None,
        "provenance": {
            "source_answer_id": "seed_ordering_sijiminfu_gugong",
            "source_answer_type": "ordering_bundle_answer",
            "evidence_ids": ["seed_source_sijiminfu"],
            "retrieval_run_id": "seed_retrieval",
        },
        "ui": {"layout": "minimal_recommendation", "show_actions": False},
    }
    assert_no_forbidden_terms(card)
    return card


def _haidilao_ordering_bundle_card() -> dict[str, Any]:
    card = {
        "id": str(uuid.uuid4()),
        "type": "recommendation_card",
        "version": "onsite_food_beijing_v1",
        "target_type": "ordering_bundle",
        "title": "番茄锅 + 牛肉/虾滑 + 蔬菜",
        "subtitle": "海底捞 · 默认 2 人",
        "decision_factor": {
            "key": "tomato_pot_stable",
            "text": "不知道怎么点时，番茄锅容错率最高。",
        },
        "image": None,
        "provenance": {
            "source_answer_id": "seed_ordering_haidilao",
            "source_answer_type": "ordering_bundle_answer",
            "evidence_ids": ["seed_source_haidilao"],
            "retrieval_run_id": "seed_retrieval",
        },
        "ui": {"layout": "minimal_recommendation", "show_actions": False},
    }
    assert_no_forbidden_terms(card)
    return card


def _venue_ordering_card(venue: str | None) -> dict[str, Any] | None:
    if venue == "海底捞":
        return _haidilao_ordering_bundle_card()
    if venue == "四季民福":
        return _ordering_bundle_card()
    if venue in OTHER_VENUE_ALIASES:
        return _generic_venue_ordering_card(venue)
    return None


def _generic_venue_ordering_card(venue: str) -> dict[str, Any]:
    route = {
        "西贝": ("黄米凉糕 + 烤羊肉串 + 莜面", "西贝 · 家庭局", "带人吃先选招牌和稳口味，莜面、羊肉串和甜口凉糕容错率最高。"),
        "陶陶居": ("虾饺 + 烧卖 + 叉烧包", "陶陶居 · 两人点心", "两个人不想点太多，先收敛到经典点心组合，稳且不浪费。"),
        "点都德": ("虾饺 + 烧卖 + 叉烧包", "点都德 · 经典点心", "第一次来点都德，先点经典点心组合，稳且不容易点多。"),
        "喜晋道": ("刀削面 + 肉丸子 + 凉菜", "喜晋道 · 到店点单", "到喜晋道不知道吃什么，先拿地方记忆点最强的面和丸子，配凉菜更稳。"),
        "聚宝源": ("清汤锅 + 手切羊肉 + 烧饼", "聚宝源 · 第一次来", "第一次来聚宝源先吃清汤和羊肉本味，烧饼补主食，最稳。"),
        "大董": ("烤鸭 + 清爽配菜 + 时蔬", "大董 · 朋友想吃烤鸭", "朋友想吃烤鸭就先围绕招牌配清爽菜，既稳也不腻。"),
        "麦当劳": ("板烧鸡腿堡套餐 + 热饮", "麦当劳 · 赶时间", "赶时间先选出餐稳定的套餐，板烧比临时尝新品更不容易踩雷。"),
    }[venue]
    title, subtitle, factor = route
    card = {
        "id": str(uuid.uuid4()),
        "type": "recommendation_card",
        "version": "onsite_food_beijing_v1",
        "target_type": "ordering_bundle",
        "title": title,
        "subtitle": subtitle,
        "decision_factor": {"key": "venue_ordering_stable", "text": factor},
        "image": None,
        "provenance": {
            "source_answer_id": f"seed_ordering_{venue}",
            "source_answer_type": "ordering_bundle_answer",
            "evidence_ids": [f"seed_source_{venue}"],
            "retrieval_run_id": "seed_retrieval",
        },
        "ui": {"layout": "minimal_recommendation", "show_actions": False},
    }
    assert_no_forbidden_terms(card)
    return card


def _product_card(message: str) -> dict[str, Any] | None:
    for keyword, title, subtitle, factor in PRODUCT_ROUTES:
        if keyword in message:
            card = {
                "id": str(uuid.uuid4()),
                "type": "recommendation_card",
                "version": "onsite_food_beijing_v1",
                "target_type": "product",
                "title": title,
                "subtitle": subtitle,
                "decision_factor": {"key": "product_stable_pick", "text": factor},
                "image": None,
                "provenance": {
                    "source_answer_id": f"seed_product_{keyword}",
                    "source_answer_type": "product_intent_answer",
                    "evidence_ids": [f"seed_source_{keyword}"],
                    "retrieval_run_id": "seed_retrieval",
                },
                "ui": {"layout": "minimal_recommendation", "show_actions": False},
            }
            assert_no_forbidden_terms(card)
            return card
    return None


def _area_help_card(message: str) -> dict[str, Any]:
    location_hint = _area_location_hint(message)
    cuisine = _food_preference_hint(message)
    return _help_card(
        message,
        title=f"{location_hint}想吃{cuisine}，求一个",
        location_state="unknown" if "很偏" in message or "贵州菜" in message else "in_area",
        context={
            "city": "北京",
            "location_hint": location_hint,
            "food_preference": cuisine,
            "task": "choose_restaurant",
            "original_query": message,
        },
    )


def _venue_help_card(message: str, *, venue: str | None = None, area: str | None = None) -> dict[str, Any]:
    venue_hint = venue or _venue_context_hint(message)
    context: dict[str, Any] = {
        "city": "北京",
        "venue": venue or "未知小店",
        "venue_hint": venue_hint,
        "task": "order_dishes",
        "menu_context": _menu_context_hint(message),
        "original_query": message,
    }
    if area:
        context["area"] = area
    return _help_card(
        message,
        title=f"{venue_hint}怎么点，求一句稳的",
        location_state="in_venue",
        context=context,
    )


def _area_location_hint(message: str) -> str:
    ordered_hints = (
        ("说不清楚", "位置说不清"),
        ("定位不准", "定位不准"),
        ("新开发区", "新开发区"),
        ("仓储园", "仓储园附近"),
        ("外环", "外环不熟区域"),
        ("不知道具体地址", "地址不明确"),
        ("工业区", "工业区"),
        ("城郊", "城郊村口" if "村口" in message else "城郊"),
        ("村口", "城郊村口"),
        ("小站", "未知车站"),
        ("无名小路", "无名小路"),
        ("小路", "郊区小路"),
        ("公园边", "公园边"),
        ("北边很远", "北边远处"),
        ("很偏", "偏远位置"),
        ("偏", "偏远位置"),
    )
    for needle, label in ordered_hints:
        if needle in message:
            return label
    return "北京附近"


def _food_preference_hint(message: str) -> str:
    ordered_foods = (
        "贵州酸汤",
        "贵州菜",
        "客家菜",
        "朝鲜族菜",
        "兰州小吃",
        "延边菜",
        "咖喱饭",
        "湖北菜",
        "严格素食",
        "藏餐",
        "海鲜",
        "火锅",
        "烧烤",
        "饺子",
        "汤",
    )
    for food in ordered_foods:
        if food in message:
            return "素食" if food == "严格素食" else food
    return "好吃的"


def _venue_context_hint(message: str) -> str:
    ordered_hints = (
        ("没有名字的小摊", "无名小摊"),
        ("路边小摊", "路边小摊"),
        ("没有线上菜单", "无线上菜单小馆"),
        ("刚开的店", "刚开新店"),
        ("店招", "店招家常菜小店"),
        ("店名不清楚", "店名不清小店"),
        ("菜单很多", "菜单很多看不懂的小店"),
        ("看不懂", "菜单看不懂的小店"),
        ("很小的面馆", "小面馆"),
        ("面馆", "小面馆"),
        ("藏在楼里", "楼里火锅店"),
        ("火锅店", "陌生火锅店"),
        ("私房菜", "私房菜"),
        ("菜单没写价格", "菜单没写价格小馆"),
        ("没写价格", "菜单没写价格小馆"),
        ("本地烧烤小店", "本地烧烤小店"),
        ("饺子铺", "陌生饺子铺"),
        ("食堂窗口", "食堂窗口"),
        ("没有评价", "无评价小店"),
        ("手写菜单", "手写菜单小店"),
        ("你没听过", "没听过的小店"),
        ("没听过", "没听过的小店"),
        ("小馆子", "陌生小馆"),
        ("小店", "陌生小店"),
    )
    for needle, label in ordered_hints:
        if needle in message:
            return label
    return "未知小店"


def _menu_context_hint(message: str) -> str:
    ordered_hints = (
        ("没有名字的小摊", "stall"),
        ("路边小摊", "stall"),
        ("小摊", "stall"),
        ("没有线上菜单", "no_online_menu"),
        ("刚开的店", "new_opening"),
        ("店招", "sign_only"),
        ("菜单很多", "hard_menu"),
        ("看不懂", "hard_menu"),
        ("没写价格", "no_price"),
        ("手写菜单", "handwritten_menu"),
        ("没有评价", "no_reviews"),
        ("老板问我要什么", "counter_ordering"),
        ("第一次来", "first_time"),
    )
    for needle, label in ordered_hints:
        if needle in message:
            return label
    return "unknown_menu"


def _help_card(
    message: str,
    *,
    title: str,
    location_state: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "help_card",
        "version": "onsite_food_beijing_v1",
        "status": "draft",
        "original_query": message,
        "title": title,
        "prompt": title,
        "location_state": location_state,
        "context": context,
        "wants": ["好吃", "别让我查"],
        "avoids": ["多个选项"],
        "constraints": [],
        "reward": {"label": "+10", "value": 10},
        "answer_stats": {"count": 0, "min_required": 3},
        "revision": {"version": 1, "last_user_feedback": None, "updated_at": _now()},
    }


def _chat_response(
    *,
    conversation_id: str,
    turn_id: str,
    response_kind: ResponseKind,
    assistant_message: str,
    location_state: str,
    ui_events: list[dict[str, Any]],
    data: dict[str, Any],
    debug: dict[str, Any] | None,
    cards: list[dict[str, Any]] | None = None,
    help_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "user_turn_id": turn_id,
        "assistant_message": assistant_message,
        "response_kind": response_kind.value,
        "location_state": location_state,
        "ui_events": ui_events,
        "data": data,
        "debug": debug,
        "cards": cards or [],
        "help_cards": help_cards or [],
        "light_events": [],
        "tool_calls": [],
        "metadata": {"runtime_path": "smoke_bypass"},
    }


def _debug(
    *,
    enabled: bool,
    selected_tool: str | None,
    location_state: str,
    source_answer_type: str | None,
    intent_key: str | None = None,
    card_id: str | None = None,
    help_card_id: str | None = None,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    return {
        "enabled": True,
        "selected_tool": selected_tool,
        "location_state": location_state,
        "intent_key": intent_key or f"smoke.{location_state}",
        "source_answer_type": source_answer_type,
        "confidence": 0.8 if card_id else 0.0,
        "retrieval_run_id": "seed_retrieval" if selected_tool else None,
        "agent_run_id": "smoke_agent_run",
        "tool_call_ids": [],
        "card_id": card_id,
        "help_card_id": help_card_id,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
