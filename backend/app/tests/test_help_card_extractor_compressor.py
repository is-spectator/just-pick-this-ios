from __future__ import annotations

from app.agent.reasoner import _draft_help_args


def _state(message: str) -> dict:
    return {
        "user_message": message,
        "turn_id": "turn-test",
        "metadata": {"question_id": "question-test", "user_id": "user-test"},
    }


def test_korea_shopping_problem_is_compressed_with_real_context() -> None:
    args = _draft_help_args(_state("韩国逛街，不去明洞，想小众"))

    assert args["title"] == "韩国小众逛街，求一个"
    assert args["context"]["area"] == "韩国"
    assert args["context"]["scene"] == "逛街"
    assert "小众" in args["wants"]
    assert "逛街顺路" in args["wants"]
    assert "明洞" in args["avoids"]
    assert args["title"] not in {"北京这顿饭，求一个", "这顿饭，求一个"}


def test_wudaokou_korean_food_title_is_specific() -> None:
    args = _draft_help_args(_state("我在五道口，想吃韩餐"))

    assert args["title"] == "五道口韩餐，求一个"
    assert args["context"]["area"] == "五道口"
    assert args["context"]["food_or_cuisine"] == "韩餐"
    assert "韩餐" in args["wants"]
    assert args["title"] not in {"北京这顿饭，求一个", "这顿饭，求一个"}


def test_haidilao_two_people_not_spicy_preserves_ordering_context() -> None:
    args = _draft_help_args(_state("我在三里屯海底捞，两个人不太能吃辣，帮我点"))

    assert args["title"] == "海底捞怎么点，求一个"
    assert args["context"]["venue"] == "海底捞"
    assert args["context"]["area"] == "三里屯"
    assert args["context"]["party_size"] == 2
    assert args["context"]["spicy_preference"] == "not_spicy"
    assert args["constraints"]["party_size"] == 2
    assert args["constraints"]["spicy_preference"] == "not_spicy"
    assert "海底捞点单" in args["wants"]
    assert "太辣" in args["avoids"]
