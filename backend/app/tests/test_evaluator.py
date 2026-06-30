from __future__ import annotations

from app.harness.evaluator import Evaluator


def test_recommendation_card_requires_single_minimal_contract() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "刀削面 + 肉丸子"},
            "decision_factor": {"text": "第一次来大同，地方记忆点最强。"},
            "evidence_ids": ["hit-1"],
        }
    )

    assert result.passed is True
    assert result.issues == []


def test_recommendation_card_allows_no_image_when_evidence_exists() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "朝阳区热干面"},
            "decision_factor": {"text": "朝阳区想吃热干面，先按明确证据选这一家。"},
            "evidence_ids": ["hit-hot-dry-noodle"],
            "image": None,
        }
    )

    assert result.passed is True
    assert "recommendation_card_missing_required_image_asset" not in result.issues


def test_recommendation_card_rejects_untrusted_present_image() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "朝阳区热干面"},
            "decision_factor": {"text": "朝阳区想吃热干面，先按明确证据选这一家。"},
            "evidence_ids": ["hit-hot-dry-noodle"],
            "image": {
                "id": "img-bad",
                "verification_status": "verified",
                "displayable": False,
                "is_ai_generated": False,
            },
        }
    )

    assert result.passed is False
    assert "recommendation_card_image_asset_not_displayable" in result.issues


def test_recommendation_card_rejects_present_image_without_source() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "朝阳区热干面"},
            "decision_factor": {"text": "朝阳区想吃热干面，先按明确证据选这一家。"},
            "evidence_ids": ["hit-hot-dry-noodle"],
            "image": {
                "id": "img-no-source",
                "verification_status": "verified",
                "displayable": True,
                "is_ai_generated": False,
            },
        }
    )

    assert result.passed is False
    assert "recommendation_card_image_asset_missing_source_url" in result.issues
    assert "recommendation_card_image_asset_missing_source_domain" in result.issues


def test_recommendation_card_accepts_verified_displayable_non_ai_image_with_source() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "朝阳区热干面"},
            "decision_factor": {"text": "朝阳区想吃热干面，先按明确证据选这一家。"},
            "evidence_ids": ["hit-hot-dry-noodle"],
            "image": {
                "id": "img-trusted",
                "verification_status": "verified",
                "displayable": True,
                "is_ai_generated": False,
                "source_url": "https://example.com/chaoyang-hot-dry-noodle",
                "source_domain": "example.com",
            },
        }
    )

    assert result.passed is True
    assert result.issues == []


def test_recommendation_card_rejects_multiple_decision_factors() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "刀削面 + 肉丸子"},
            "decision_factors": [
                {"text": "地方记忆点强"},
                {"text": "离你近"},
            ],
            "decision_factor": [{"text": "地方记忆点强"}, {"text": "离你近"}],
            "evidence_ids": ["hit-1"],
        }
    )

    assert result.passed is False
    assert "recommendation_card_must_use_singular_decision_factor" in result.issues
    assert "recommendation_card_decision_factor_must_be_single" in result.issues


def test_help_card_generic_payload_fails_quality_gate() -> None:
    result = Evaluator().evaluate_help_card(
        {
            "title": "北京这顿饭，求一个",
            "context": {"city": "北京"},
            "wants": ["好吃", "别让我查"],
            "avoids": ["多个选项"],
        }
    )

    assert result.passed is False
    issues = set(result.issues)
    assert issues & {"generic_title", "help_card_title_too_generic"}
    assert issues & {"generic_wants", "help_card_wants_too_generic"}
    assert issues & {"product_rule_in_avoids", "help_card_avoids_too_generic"}


def test_haidilao_sanlitun_orders_in_venue_bundle() -> None:
    result = Evaluator().evaluate_response(
        "我在海底捞三里屯店，两个人不吃辣帮我点什么",
        {
            "location_state": "in_venue",
            "data": {
                "recommendation_card": {
                    "title": "海底捞三里屯两人不辣点菜组合",
                    "location_state": "in_venue",
                    "target_type": "ordering_bundle",
                    "item": {"title": "海底捞三里屯两人不辣点菜组合"},
                    "decision_factor": {"text": "在店内点菜场景，比附近川菜候选更匹配。"},
                    "evidence_ids": ["menu-hit-1"],
                }
            },
            "ui_events": [{"type": "show_recommendation_card", "card_id": "card-haidilao"}],
        },
    )

    assert result.passed is True
    assert "venue_order_should_route_in_venue" not in result.issues
    assert "venue_order_should_return_ordering_bundle" not in result.issues
    assert "haidilao_route_overridden_by_area_restaurant" not in result.issues


def test_haidilao_sanlitun_rejects_area_restaurant_candidate_leak() -> None:
    result = Evaluator().evaluate_response(
        "我在海底捞三里屯店，两个人不吃辣帮我点什么",
        {
            "location_state": "in_area",
            "data": {
                "recommendation_card": {
                    "title": "三里屯川菜馆候选",
                    "location_state": "in_area",
                    "target_type": "restaurant",
                    "item": {"title": "三里屯川菜馆候选"},
                    "decision_factor": {"text": "附近餐厅看起来不错。"},
                    "evidence_ids": ["area-hit-1"],
                }
            },
            "ui_events": [{"type": "show_recommendation_card", "card_id": "card-area"}],
        },
    )

    assert result.passed is False
    assert "venue_order_should_route_in_venue" in result.issues
    assert "venue_order_should_return_ordering_bundle" in result.issues
    assert "haidilao_route_overridden_by_area_restaurant" in result.issues
