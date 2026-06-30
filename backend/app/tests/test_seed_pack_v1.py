from __future__ import annotations

from app.services.seed_service import (
    SEED_PACK_MIN_ANSWER_COUNT,
    SEED_PACK_SOURCE_TYPE,
    _seed_pack_intent_answers,
    load_seed_pack_entries,
)


def test_intent_seed_pack_v1_has_required_coverage() -> None:
    entries = load_seed_pack_entries()

    assert len(entries) >= SEED_PACK_MIN_ANSWER_COUNT
    assert len({(entry.get("city"), entry.get("area") or entry.get("venue")) for entry in entries}) >= 20
    assert {entry.get("target_type") for entry in entries} >= {"restaurant", "ordering_bundle", "place"}
    assert {entry.get("location_state") for entry in entries} >= {"in_area", "in_venue"}

    for entry in entries:
        assert entry.get("intent_key")
        assert entry.get("intent_name")
        assert entry.get("answer_title")
        assert entry.get("answer_summary")
        assert entry.get("decision_factor")
        assert entry.get("location_state") in {"in_area", "in_venue"}
        assert entry.get("target_type") in {"restaurant", "ordering_bundle", "place"}
        assert isinstance(entry.get("constraints"), dict)
        assert entry["constraints"].get("location_state") == entry.get("location_state")
        assert entry["constraints"].get("target_type") == entry.get("target_type")


def test_intent_seed_pack_rows_are_active_approved_intent_answers() -> None:
    rows = _seed_pack_intent_answers(load_seed_pack_entries())

    assert len(rows) >= SEED_PACK_MIN_ANSWER_COUNT
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["source_ref_id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["source_type"] == SEED_PACK_SOURCE_TYPE
        assert row["is_active"] is True
        assert row["image_asset_id"] is None
        assert row["evidence_json"]["approved"] is True
        assert row["evidence_json"]["decision_factor"]["text"]
        assert row["answer_title"]
        assert row["answer_summary"]
