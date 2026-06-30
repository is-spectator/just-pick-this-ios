from __future__ import annotations

from types import SimpleNamespace

from app.services.chat import _amap_area_decision_text, _area_food_preference, _choose_amap_candidate
from app.services.prompt_config import DEFAULT_PROMPT_CONFIGS


def _policy_config() -> dict:
    return DEFAULT_PROMPT_CONFIGS["area_food_evidence_policy"]["config_json"]


def test_cantonese_profile_rejects_hunan_and_heavy_spicy() -> None:
    preference = _area_food_preference("我是广东人，在望京SOHO想吃饭", _policy_config())

    assert preference["rule_name"] == "cantonese_profile"
    assert preference["search_keyword"] == "粤菜"
    assert {"湘菜", "重辣", "火锅"}.issubset(set(preference["reject_terms"]))

    candidate = _choose_amap_candidate(
        [
            SimpleNamespace(name="望京湘菜重辣小馆", type="湘菜", address="望京", distance_meters=80),
            SimpleNamespace(name="顺德粤菜茶餐厅", type="粤菜", address="望京", distance_meters=500),
        ],
        prefer_terms=preference["prefer_terms"],
        reject_terms=preference["reject_terms"],
        require_preferred_match=preference["require_preferred_match"],
    )

    assert candidate.name == "顺德粤菜茶餐厅"


def test_jiangzhe_profile_prefers_light_local_cuisines() -> None:
    preference = _area_food_preference("江浙用户想吃清淡一点", _policy_config())

    assert preference["rule_name"] == "jiangzhe_profile"
    assert preference["search_keyword"] == "杭帮菜"
    assert {"清淡", "本帮", "杭帮", "淮扬"}.issubset(set(preference["prefer_terms"]))


def test_parents_profile_prefers_quiet_light_no_queue() -> None:
    preference = _area_food_preference("带爸妈在附近吃饭", _policy_config())

    assert preference["rule_name"] == "parents_profile"
    assert {"安静", "清淡", "不排队"}.issubset(set(preference["prefer_terms"]))
    assert {"重辣", "排队"}.issubset(set(preference["reject_terms"]))


def test_date_profile_prefers_quiet_atmosphere_no_queue() -> None:
    preference = _area_food_preference("今晚约会吃饭", _policy_config())

    assert preference["rule_name"] == "date_profile"
    assert {"安静", "氛围", "不排队"}.issubset(set(preference["prefer_terms"]))
    assert "排队" in preference["reject_terms"]


def test_non_spicy_profile_filters_heavy_spicy_and_hotpot() -> None:
    preference = _area_food_preference("我不太能吃辣，找个附近餐厅", _policy_config())

    assert preference["rule_name"] == "non_spicy_profile"
    assert {"重辣", "火锅"}.issubset(set(preference["reject_terms"]))
    assert preference["require_preferred_match"] is True

    candidate = _choose_amap_candidate(
        [
            SimpleNamespace(name="红油麻辣火锅", type="火锅", address="附近", distance_meters=60),
            SimpleNamespace(name="清淡杭帮小馆", type="杭帮菜", address="附近", distance_meters=450),
        ],
        prefer_terms=preference["prefer_terms"],
        reject_terms=preference["reject_terms"],
        require_preferred_match=preference["require_preferred_match"],
    )

    assert candidate.name == "清淡杭帮小馆"


def _memory_summary(**summary: list[dict[str, object]]) -> dict:
    return {"version": "user_preference_memory_v1", "summary": summary}


def test_same_area_query_uses_cantonese_user_memory() -> None:
    preference = _area_food_preference(
        "我在望京SOHO，帮我选一家",
        _policy_config(),
        user_preference_memory=_memory_summary(top_cuisines=[{"value": "粤菜", "score": 3}]),
    )

    assert preference["source"] == "user_memory"
    assert preference["rule_name"] == "cantonese_profile"
    assert preference["search_keyword"] == "粤菜"
    assert "广东人" in preference["decision_prefix"]


def test_same_area_query_uses_jiangzhe_user_memory() -> None:
    preference = _area_food_preference(
        "我在望京SOHO，帮我选一家",
        _policy_config(),
        user_preference_memory=_memory_summary(top_cuisines=[{"value": "杭帮菜", "score": 2}]),
    )

    assert preference["source"] == "user_memory"
    assert preference["rule_name"] == "jiangzhe_profile"
    assert preference["search_keyword"] == "杭帮菜"
    assert "江浙" in preference["decision_prefix"]


def test_same_area_query_uses_non_spicy_user_memory() -> None:
    preference = _area_food_preference(
        "我在望京SOHO，帮我选一家",
        _policy_config(),
        user_preference_memory=_memory_summary(spice_preferences=[{"value": "not_spicy", "score": 4}]),
    )

    assert preference["source"] == "user_memory"
    assert preference["rule_name"] == "non_spicy_profile"
    assert preference["display_food"] == "清淡口味"
    assert preference["require_preferred_match"] is True


def test_same_area_query_different_memories_produce_different_decision_factors() -> None:
    query = "我在望京SOHO，帮我选一家"
    cantonese = _area_food_preference(
        query,
        _policy_config(),
        user_preference_memory=_memory_summary(top_cuisines=[{"value": "粤菜", "score": 3}]),
    )
    jiangzhe = _area_food_preference(
        query,
        _policy_config(),
        user_preference_memory=_memory_summary(top_cuisines=[{"value": "杭帮菜", "score": 2}]),
    )

    cantonese_factor = _amap_area_decision_text(
        area="望京SOHO",
        display_food=cantonese["display_food"],
        route_summary="步行约 8 分钟",
        decision_prefix=cantonese["decision_prefix"],
    )
    jiangzhe_factor = _amap_area_decision_text(
        area="望京SOHO",
        display_food=jiangzhe["display_food"],
        route_summary="步行约 8 分钟",
        decision_prefix=jiangzhe["decision_prefix"],
    )

    assert cantonese_factor != jiangzhe_factor
    assert "广东人" in cantonese_factor
    assert "江浙" in jiangzhe_factor
