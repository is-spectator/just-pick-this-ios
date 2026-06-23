from __future__ import annotations

from app.retrieval.evidence_pack import build_evidence_pack, summarize_evidence_pack


def test_evidence_pack_groups_layers_and_flags() -> None:
    pack = build_evidence_pack(
        [
            {
                "source_id": "hit-intent",
                "source_type": "intent_answer",
                "title": "大同喜晋道",
                "score": 0.93,
                "payload": {
                    "retrieval_hit_id": "hit-intent",
                    "intent_answer_id": "answer-1",
                    "image_asset_id": "image-1",
                    "has_answer_evidence": True,
                    "has_verified_non_ai_image": True,
                    "evidence_layers": ["intent_answer", "image_asset"],
                },
            },
            {
                "source_id": "hit-human",
                "source_type": "help_answer",
                "title": "来一句",
                "score": 0.82,
                "payload": {
                    "help_answer_id": "help-answer-1",
                    "help_card_id": "help-card-1",
                    "evidence_layers": ["human_answer"],
                },
            },
            {
                "source_id": "hit-web",
                "source_type": "web_result",
                "title": "网页参考",
                "score": 0.72,
                "payload": {"web_reference": True, "source_url": "https://example.com"},
            },
        ],
        retrieval_run={"id": "retrieval-1", "query": "大同喜晋道吃什么"},
    )

    layer_counts = {layer["type"]: layer["count"] for layer in pack["layers"]}
    assert pack["version"] == "evidence_pack_v1"
    assert pack["retrieval_run_id"] == "retrieval-1"
    assert pack["hit_count"] == 3
    assert layer_counts["intent_answer"] == 1
    assert layer_counts["human_answer"] == 1
    assert layer_counts["web_result"] == 1
    assert layer_counts["image_asset"] == 1
    assert pack["has_local_memory"] is True
    assert pack["has_human_evidence"] is True
    assert pack["has_web_evidence"] is True
    assert pack["has_verified_image"] is True
    assert pack["has_card_ready_evidence"] is True
    assert "verified_image" not in pack["missing_layers"]
    assert [item["id"] for item in pack["strongest_evidence"]] == [
        "hit-intent",
        "hit-human",
        "hit-web",
    ]


def test_evidence_pack_normalizes_place_and_route_evidence() -> None:
    pack = build_evidence_pack(
        [
            {
                "source_id": "poi-hit",
                "source_type": "amap_poi_candidate",
                "title": "某某热干面",
                "score": 0.91,
                "payload": {
                    "has_answer_evidence": True,
                    "has_place_evidence": True,
                    "has_taste_or_preference_evidence": True,
                    "evidence_layers": ["amap_poi", "route", "decision_factor"],
                    "decision_factor": "朝阳区附近想吃热干面，先选这家，步行约 8 分钟。",
                    "place": {
                        "provider": "amap",
                        "poi_id": "poi-1",
                        "name": "某某热干面",
                        "address": "北京市朝阳区",
                        "location": {"lng": 116.45, "lat": 39.92, "coord_type": "gcj02"},
                    },
                    "action": {"type": "open_amap", "uri": "amapuri://route/plan/"},
                    "route": {"summary_text": "步行约 8 分钟"},
                },
            }
        ],
        retrieval_run={"id": "retrieval-place"},
    )

    first = pack["strongest_evidence"][0]
    assert pack["has_place_evidence"] is True
    assert pack["has_route_evidence"] is True
    assert pack["has_card_ready_evidence"] is True
    assert first["place"]["location"]["coord_type"] == "gcj02"
    assert first["action_type"] == "open_amap"
    assert "place_evidence" not in pack["missing_layers"]


def test_evidence_pack_limits_strongest_evidence_and_summarizes() -> None:
    hits = [
        {
            "source_id": f"hit-{index}",
            "source_type": "web_result",
            "title": f"网页 {index}",
            "score": index / 10,
            "payload": {"web_reference": True},
        }
        for index in range(10)
    ]

    pack = build_evidence_pack(hits, retrieval_run={"id": "retrieval-web"}, max_items=5)
    summary = summarize_evidence_pack(pack)

    assert [item["id"] for item in pack["strongest_evidence"]] == [
        "hit-9",
        "hit-8",
        "hit-7",
        "hit-6",
        "hit-5",
    ]
    assert summary["retrieval_run_id"] == "retrieval-web"
    assert summary["layer_counts"]["web_result"] == 10
    assert summary["has_web_evidence"] is True
