from __future__ import annotations

from app.harness.evidence_evaluator import evaluate_retrieval_hits, is_card_ready_hit


def test_amap_poi_only_generic_decision_is_not_enough_evidence() -> None:
    hit = {
        "score": 0.92,
        "payload": {
            "has_answer_evidence": True,
            "has_place_evidence": True,
            "place": {"provider": "amap", "name": "附近餐厅"},
            "action": {"type": "open_amap", "uri": "https://uri.amap.com/navigation?x=1"},
            "source_answer_type": "amap_poi_candidate",
            "decision_factor": "适合现在直接做决定。",
            "evidence_layers": ["amap_poi"],
        },
    }

    result = evaluate_retrieval_hits([hit])

    assert result["can_recommend"] is False
    assert "taste_or_preference_evidence" in result["missing_requirements"]
    assert is_card_ready_hit(hit) is False


def test_amap_poi_with_route_and_food_decision_is_card_ready() -> None:
    hit = {
        "score": 0.92,
        "payload": {
            "has_answer_evidence": True,
            "has_place_evidence": True,
            "has_taste_or_preference_evidence": True,
            "place": {"provider": "amap", "name": "汉口热干面"},
            "route": {"summary_text": "步行约 5 分钟"},
            "action": {"type": "open_amap", "uri": "https://uri.amap.com/navigation?x=1"},
            "source_answer_type": "amap_poi_candidate",
            "decision_factor": "朝阳区附近想吃热干面，先选这家，步行约 5 分钟。",
            "evidence_layers": ["amap_poi", "route", "taste_or_preference", "decision_factor"],
        },
    }

    result = evaluate_retrieval_hits([hit])

    assert result["can_recommend"] is True
    assert result["missing_requirements"] == []
    assert is_card_ready_hit(hit) is True


def test_web_reference_without_answer_or_image_keeps_legacy_missing_requirements() -> None:
    result = evaluate_retrieval_hits(
        [
            {
                "score": 0.74,
                "payload": {
                    "web_reference": True,
                    "has_answer_evidence": False,
                    "has_verified_non_ai_image": False,
                    "reference_answer": "只有网页片段",
                },
            }
        ]
    )

    assert result["can_recommend"] is False
    assert result["missing_requirements"] == [
        "answer_evidence",
        "verified_non_ai_image",
    ]
