from __future__ import annotations

from app.services.help_service import assess_one_liner_quality, normalize_one_liner_key


def test_one_liner_quality_rejects_obvious_spam() -> None:
    for text in ["随便", "不知道", "哈哈哈哈", "1111"]:
        quality = assess_one_liner_quality(text)
        assert quality.accepted is False
        assert quality.reason


def test_one_liner_quality_accepts_specific_human_evidence() -> None:
    quality = assess_one_liner_quality("去圣水更稳，小店密度高。")

    assert quality.accepted is True
    assert quality.normalized_key == "去圣水更稳小店密度高"


def test_one_liner_duplicate_key_ignores_punctuation_and_spaces() -> None:
    assert normalize_one_liner_key("去圣水更稳，小店密度高。") == normalize_one_liner_key("去圣水更稳 小店密度高")
