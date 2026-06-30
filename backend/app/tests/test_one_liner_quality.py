from __future__ import annotations

from app.services.help_service import (
    assess_one_liner_quality,
    detect_help_card_abuse,
    detect_one_liner_abuse,
    normalize_one_liner_key,
)


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


def test_help_card_abuse_detects_unsafe_feed_content_without_blocking_normal_requests() -> None:
    unsafe = detect_help_card_abuse(
        title="朝阳区热干面求一个，加我微信 vx123456",
        context_text="我把联系方式放这里。",
    )
    assert unsafe.unsafe is True
    assert "contact_spam" in unsafe.issues
    assert unsafe.priority <= 20

    illegal = detect_help_card_abuse(title="帮我找办假证的人", context_text="")
    assert illegal.unsafe is True
    assert "illegal_request" in illegal.issues

    privacy = detect_help_card_abuse(title="帮我开盒这个人", context_text="想查他的家庭住址")
    assert privacy.unsafe is True
    assert "privacy_harm" in privacy.issues

    normal = detect_help_card_abuse(
        title="朝阳区热干面求一个",
        context_text="想找现在能直接去、别太远的一家。",
        payload={"wants": ["热干面"], "avoids": ["太远"]},
    )
    assert normal.unsafe is False
