from __future__ import annotations

from types import SimpleNamespace

from app.services.chat import _area_food_preference, _choose_amap_candidate
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
