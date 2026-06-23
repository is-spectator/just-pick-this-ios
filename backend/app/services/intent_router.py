from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChitchatDecision:
    intent_key: str
    assistant_message: str


@dataclass(frozen=True)
class ClarificationDecision:
    intent_key: str
    missing_slots: list[str]
    question: str
    assistant_message: str
    location_state: str = "unknown"


_GREETING_TERMS = ("你好", "嗨", "哈喽", "早上好", "晚上好")
_THANKS_TERMS = ("谢谢", "谢谢你", "感谢", "辛苦了")
_IDENTITY_TERMS = ("你是谁", "你叫什么", "你叫什么名字", "你能干什么", "你能做什么", "皮皮是谁")
_APP_HELP_TERMS = ("怎么用", "帮助", "help", "说明")
_GOODBYE_TERMS = ("再见", "拜拜", "下次见", "先这样拜拜")
_CASUAL_TERMS = (
    "哈哈",
    "好的",
    "明白了",
    "你好吗",
    "皮皮在吗",
    "讲个短笑话",
    "夸夸我",
    "今天心情不好",
    "今天天气真不错",
    "刚下班有点累",
    "随便聊两句",
    "随便说点什么",
    "随便说点",
    "晚安",
    "我现在没什么事",
)

_ORDER_WITHOUT_VENUE_TERMS = (
    "帮我点菜",
    "怎么点",
    "吃什么菜",
)
_UNKNOWN_VENUE_CONTEXT_TERMS = (
    "你没听过的小店",
    "没听过的小店",
    "没有线上菜单",
    "小馆子",
    "小馆",
    "小店",
    "手写菜单",
    "刚开的店",
    "刚开",
    "网上应该没资料",
    "店招",
    "家常菜",
    "菜单很多看不懂",
    "菜单看不懂",
    "看不懂",
    "很小的面馆",
    "小面馆",
    "藏在楼里",
    "没看到评价",
    "私房菜",
    "菜单没写价格",
    "路边小摊",
    "没有名字的小摊",
    "老板问我要什么",
    "老板问",
)
_GENERIC_FOOD_TERMS = (
    "我想吃饭",
    "我饿了",
    "吃什么",
    "想吃点东西",
    "帮我选一家",
    "附近有什么好吃的",
    "给我推荐个餐厅",
    "附近找个餐厅",
    "想吃辣",
    "两个人吃饭",
    "想吃点不贵",
    "我在北京吃什么",
    "带朋友吃饭去哪",
    "想吃清淡",
    "想吃火锅",
    "周末聚餐",
    "一个人吃饭",
    "太饿了",
    "想找个坐一会",
    "帮我安排晚饭",
    "想吃北京菜",
    "想喝咖啡",
    "想吃甜品",
    "想吃小吃",
    "带爸妈吃饭去哪",
    "想吃特别一点",
    "想吃健康点",
    "快点帮我选一个",
    "想找个安静地方",
    "想吃素",
    "想找个地方待一会",
    "不吃辣帮我选",
)
_CUISINE_ONLY_TERMS = ("想吃川菜", "想吃烤鸭", "想吃火锅", "想吃北京菜")
_GENERIC_NON_FOOD_TERMS = (
    "想买个小屏",
    "想买个充电宝",
    "出去玩去哪",
    "想逛街去哪",
    "想买伴手礼",
    "附近咖啡给我选一个",
    "菜单太多帮我看",
    "半天去哪玩",
    "我想买电烙铁顺便附近吃点啥",
    "我拍了菜单但你看不到帮我点",
)
_KNOWN_AREA_TERMS = (
    "三里屯",
    "朝阳区",
    "朝阳soho",
    "朝阳SOHO",
    "南锣鼓巷",
    "王府井",
    "故宫",
    "前门",
    "国贸",
    "望京",
    "五道口",
    "簋街",
    "西单",
    "后海",
    "南京西路",
    "徐家汇",
    "静安寺",
    "陆家嘴",
    "春熙路",
    "太古里",
    "宽窄巷子",
    "牛街",
    "天河",
    "南山",
)
_KNOWN_VENUE_TERMS = (
    "海底捞",
    "四季民福",
    "西贝",
    "陶陶居",
    "喜晋道",
    "麦当劳",
    "聚宝源",
    "大董",
    "点都德",
)


def detect_chitchat(message: str) -> ChitchatDecision | None:
    normalized = _normalize(message)
    compact = normalized.replace("，", "").replace(",", "").replace("。", "").replace("！", "").replace("?", "")
    if _contains_any(normalized, _GREETING_TERMS):
        return ChitchatDecision(
            intent_key="chitchat.greeting",
            assistant_message="你好，我是皮皮。你到店了、到某个区域了，都可以直接让我替你选一个。",
        )
    if _contains_any(normalized, _THANKS_TERMS):
        return ChitchatDecision(
            intent_key="chitchat.thanks",
            assistant_message="不客气，我在。下次你纠结吃什么或怎么点，直接叫皮皮帮你选一个。",
        )
    if _contains_any(normalized, _IDENTITY_TERMS):
        return ChitchatDecision(
            intent_key="chitchat.identity",
            assistant_message="我是皮皮，可以在你到店或到一个区域时，帮你把选择收成一个。",
        )
    if _contains_any(normalized, _GOODBYE_TERMS):
        return ChitchatDecision(
            intent_key="chitchat.goodbye",
            assistant_message="再见，我在。下次想吃饭、点菜、逛哪里，都可以叫皮皮。",
        )
    if compact == "晚安":
        return ChitchatDecision(
            intent_key="chitchat.good_night",
            assistant_message="晚安，我在。明天需要选吃的，再叫皮皮帮你。",
        )
    if _contains_any(normalized, _CASUAL_TERMS):
        return ChitchatDecision(
            intent_key="chitchat.smalltalk",
            assistant_message="我在，皮皮可以陪你聊两句；真要做选择时，我也可以直接帮你定一个。",
        )
    return None


def detect_app_help(message: str) -> ChitchatDecision | None:
    normalized = _normalize(message)
    if _contains_any(normalized, _APP_HELP_TERMS):
        return ChitchatDecision(
            intent_key="chitchat.app_help",
            assistant_message="告诉我你在哪、想做什么；我会直接帮你收成一个选择，拿不准时也可以帮你问别人。",
        )
    return None


def detect_clarification_needed(message: str) -> ClarificationDecision | None:
    normalized = _normalize(message)
    compact = _strip_punctuation(normalized)
    has_area = _contains_any(normalized, _KNOWN_AREA_TERMS) or _contains_any(compact, _KNOWN_AREA_TERMS)
    has_venue = _contains_any(normalized, _KNOWN_VENUE_TERMS) or _contains_any(compact, _KNOWN_VENUE_TERMS)
    has_travel_shopping_context = any(city in compact for city in ("曼谷", "首尔", "韩国", "京都", "东京", "香港", "台北")) and any(
        hint in compact for hint in ("伴手礼", "美妆", "逛", "去哪", "选一个地方", "买")
    )

    if has_venue:
        return None
    if _has_unknown_venue_context(compact):
        return None
    if has_travel_shopping_context:
        return None
    if has_area and not _is_city_only_food_question(compact):
        return None

    if "树莓派" in compact and "晚饭" in compact:
        return ClarificationDecision(
            intent_key="clarification.mixed_domain",
            missing_slots=["decision_domain"],
            question="你想先选吃饭还是先选东西？",
            assistant_message="这像是两个选择混在一起了。你想先让我帮你选吃饭，还是先选要买的东西？",
        )

    if _contains_any(normalized, _ORDER_WITHOUT_VENUE_TERMS):
        return ClarificationDecision(
            intent_key="clarification.missing_venue",
            missing_slots=["venue"],
            question="你在哪家店？",
            assistant_message="你在哪家店？把店名告诉我，我直接帮你点。",
        )
    if (
        _contains_any(normalized, _CUISINE_ONLY_TERMS)
        or _contains_any(normalized, _GENERIC_FOOD_TERMS)
        or _contains_any(compact, _GENERIC_FOOD_TERMS)
        or _contains_any(compact, _GENERIC_NON_FOOD_TERMS)
        or _is_city_only_food_question(compact)
    ):
        return ClarificationDecision(
            intent_key="clarification.missing_area",
            missing_slots=["area"],
            question="你现在在哪个区域？",
            assistant_message="你现在在哪个位置？告诉我附近区域、店名或想吃什么口味，我直接帮你选一个。",
        )
    return None


def _has_unknown_venue_context(message: str) -> bool:
    if not _contains_any(message, _UNKNOWN_VENUE_CONTEXT_TERMS):
        return False
    return any(term in message for term in ("我在", "现在在", "坐在", "到店", "老板", "菜单", "店", "小馆", "小摊", "面馆"))


def _contains_any(message: str, terms: tuple[str, ...]) -> bool:
    return any(term in message for term in terms)


def _normalize(message: str) -> str:
    return "".join(str(message).strip().split())


def _strip_punctuation(message: str) -> str:
    output = message
    for char in ("，", ",", "。", "！", "!", "？", "?", "、", "；", ";", "：", ":"):
        output = output.replace(char, "")
    return output


def _is_city_only_food_question(message: str) -> bool:
    return any(city in message for city in ("北京", "上海", "广州", "深圳", "成都")) and any(
        term in message for term in ("吃什么", "吃啥", "吃饭", "去哪吃")
    ) and not _contains_any(message, _KNOWN_AREA_TERMS + _KNOWN_VENUE_TERMS)
