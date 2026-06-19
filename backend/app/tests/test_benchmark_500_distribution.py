from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.eval.reporting import benchmark_coverage


BENCHMARK_PATH = Path(__file__).resolve().parents[3] / "benchmarks/pipi_onsite_500_v1.json"

EXPECTED_DISTRIBUTION = {
    "by_category": {
        "area_food": 100,
        "edge_adversarial": 20,
        "help_card_update": 60,
        "one_liner_finalize": 40,
        "product_decision": 60,
        "smalltalk_app_help_unknown": 50,
        "travel_shopping": 80,
        "venue_order": 90,
    },
    "by_expected_kind": {
        "chitchat": 50,
        "clarification": 20,
        "help_card_draft": 140,
        "recommendation_card": 290,
    },
    "by_location_state": {
        "in_area": 160,
        "in_venue": 90,
        "unknown": 250,
    },
    "by_target_type": {
        "none": 210,
        "ordering_bundle": 90,
        "product": 60,
        "restaurant": 140,
    },
}


def test_pipi_onsite_500_distribution_is_stable() -> None:
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["suite_id"] == "pipi_onsite_500_v1"
    assert payload["target_case_count"] == 500
    assert payload["is_minimal_seed"] is False
    assert len(cases) == 500
    assert len({case["id"] for case in cases}) == 500
    assert payload["expected_distribution"] == EXPECTED_DISTRIBUTION

    assert Counter(case["category"] for case in cases) == EXPECTED_DISTRIBUTION["by_category"]
    assert (
        Counter(case["expected"]["response_kind"] for case in cases)
        == EXPECTED_DISTRIBUTION["by_expected_kind"]
    )
    assert (
        Counter(case["expected"]["location_state"] for case in cases)
        == EXPECTED_DISTRIBUTION["by_location_state"]
    )
    assert (
        Counter(case["expected"].get("target_type", "none") for case in cases)
        == EXPECTED_DISTRIBUTION["by_target_type"]
    )

    coverage = benchmark_coverage(cases)
    assert coverage["schema_valid"] is True
    assert coverage["distribution_valid"] is True
    assert coverage["by_category"] == EXPECTED_DISTRIBUTION["by_category"]
    assert coverage["by_expected_kind"] == EXPECTED_DISTRIBUTION["by_expected_kind"]
    assert coverage["by_location_state"] == EXPECTED_DISTRIBUTION["by_location_state"]
    assert coverage["by_target_type"] == EXPECTED_DISTRIBUTION["by_target_type"]
