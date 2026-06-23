from __future__ import annotations

from app.services.help_service import assess_one_liner_quality, detect_one_liner_abuse, normalize_one_liner_key


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


def test_one_liner_abuse_detects_contact_spam_without_blocking_normal_advice() -> None:
    spam = detect_one_liner_abuse("加我微信 vx123456，我详细告诉你")
    assert spam.unsafe is True
    assert "contact_spam" in spam.issues
    assert spam.priority <= 20

    normal = detect_one_liner_abuse("可以提前用微信小程序排队，别现场硬等。")
    assert normal.unsafe is False
