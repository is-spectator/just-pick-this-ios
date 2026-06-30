from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ImageAsset, Intent, IntentAnswer


DATONG_IMAGE_ASSET_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
SEONGSU_IMAGE_ASSET_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
SIJIMINFU_IMAGE_ASSET_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")
FOOD_INTENT_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
SHOPPING_INTENT_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
FOOD_INTENT_ANSWER_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
SHOPPING_INTENT_ANSWER_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")
SIJIMINFU_INTENT_ANSWER_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")
SEED_PACK_SOURCE_TYPE = "curated_seed_pack_v1"
SEED_PACK_MIN_ANSWER_COUNT = 100
SEED_PACK_NAMESPACE = uuid.UUID("99999999-9999-4999-8999-999999999999")
SEED_PACK_PATH = Path(__file__).resolve().parents[1] / "data" / "intent_seed_pack_v1.json"


def seed_initial_data(session: Session) -> None:
    """Seed deterministic curated data used by first-stage local development."""

    _upsert_all(session, ImageAsset, _image_assets())
    _upsert_all(session, Intent, _intents())
    _upsert_all(session, IntentAnswer, _intent_answers())
    seed_intent_answer_pack(session)
    session.commit()


def _upsert_all(session: Session, model: type, rows: Iterable[dict]) -> None:
    for row in rows:
        instance = session.scalar(select(model).where(model.id == row["id"]))
        if instance is None:
            session.add(model(**row))
            continue

        for key, value in row.items():
            setattr(instance, key, value)


def seed_intent_answer_pack(session: Session) -> int:
    """Load the reviewed v1 IntentAnswer seed pack and return row count."""

    rows = _seed_pack_rows()
    _upsert_all(session, Intent, _seed_pack_intents(rows))
    _upsert_all(session, IntentAnswer, _seed_pack_intent_answers(rows))
    return len(rows)


def seed_pack_answer_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(IntentAnswer).where(IntentAnswer.source_type == SEED_PACK_SOURCE_TYPE)
        )
        or 0
    )


def load_seed_pack_entries() -> list[dict[str, Any]]:
    payload = json.loads(SEED_PACK_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("intent_seed_pack_v1 entries must be a list")
    return [dict(entry) for entry in entries]


def _seed_pack_rows() -> list[dict[str, Any]]:
    rows = load_seed_pack_entries()
    if len(rows) < SEED_PACK_MIN_ANSWER_COUNT:
        raise ValueError(f"intent seed pack must contain at least {SEED_PACK_MIN_ANSWER_COUNT} entries")
    return rows


def _seed_pack_intents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intents: dict[str, dict[str, Any]] = {}
    for row in rows:
        intent_key = str(row.get("intent_key") or "").strip()
        if not intent_key:
            raise ValueError("seed pack row missing intent_key")
        intents[intent_key] = {
            "id": _seed_uuid(f"intent:{intent_key}"),
            "key": intent_key,
            "name": str(row.get("intent_name") or intent_key),
            "description": f"Seed pack v1 intent for {row.get('domain') or 'decision'}",
            "examples_json": [{"text": str(row.get("answer_title") or row.get("answer_summary") or intent_key)}],
            "is_active": True,
        }
    return list(intents.values())


def _seed_pack_intent_answers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for row in rows:
        intent_key = str(row.get("intent_key") or "").strip()
        source_ref_id = f"seed-pack-v1:{intent_key}"
        constraints = dict(row.get("constraints") or {})
        decision_factor = str(row.get("decision_factor") or row.get("answer_summary") or "")
        answers.append(
            {
                "id": _seed_uuid(f"answer:{source_ref_id}"),
                "intent_id": _seed_uuid(f"intent:{intent_key}"),
                "image_asset_id": None,
                "answer_text": str(row.get("answer_summary") or decision_factor or row.get("answer_title") or ""),
                "intent_key": intent_key,
                "intent_text": str(row.get("intent_name") or intent_key),
                "answer_title": str(row.get("answer_title") or intent_key),
                "answer_summary": str(row.get("answer_summary") or decision_factor),
                "constraints_json": constraints,
                "source_type": SEED_PACK_SOURCE_TYPE,
                "source_ref_id": source_ref_id,
                "confidence": float(row.get("confidence") or 0.75),
                "success_count": 0,
                "rejection_count": 0,
                "last_used_at": None,
                "locale": "zh-CN",
                "tags_json": [str(tag) for tag in row.get("tags") or []],
                "evidence_json": {
                    "source": SEED_PACK_SOURCE_TYPE,
                    "pack_id": "intent_seed_pack_v1",
                    "approved": True,
                    "target_type": row.get("target_type"),
                    "location_state": row.get("location_state"),
                    "decision_factor": {"text": decision_factor, "key": str(row.get("task") or "seed_pack")},
                    "constraints": constraints,
                },
                "priority": int(row.get("priority") or 80),
                "is_active": True,
            }
        )
    return answers


def _seed_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(SEED_PACK_NAMESPACE, value)


def _image_assets() -> list[dict]:
    return [
        {
            "id": DATONG_IMAGE_ASSET_ID,
            "source_type": "curated",
            "url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624",
            "thumbnail_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=480",
            "source_url": "https://unsplash.com/photos/1569718212165-3a8278d5f624",
            "source_domain": "unsplash.com",
            "credit": "Product reference image",
            "verified": True,
            "verification_status": "verified",
            "is_ai_generated": False,
            "ai_generated_risk": "low",
            "displayable": True,
            "place_key": "datong-xijindao",
            "item_key": "knife-cut-noodles-meatball",
            "query_text": "大同喜晋道 刀削面 肉丸子",
            "license_note": "参考图片",
            "alt_text": "一碗面食参考图片。",
            "metadata_json": {"seed": True},
        },
        {
            "id": SEONGSU_IMAGE_ASSET_ID,
            "source_type": "curated",
            "url": "https://images.unsplash.com/photo-1517154421773-0529f29ea451",
            "thumbnail_url": "https://images.unsplash.com/photo-1517154421773-0529f29ea451?w=480",
            "source_url": "https://unsplash.com/photos/1517154421773-0529f29ea451",
            "source_domain": "unsplash.com",
            "credit": "Product reference image",
            "verified": True,
            "verification_status": "verified",
            "is_ai_generated": False,
            "ai_generated_risk": "low",
            "displayable": True,
            "place_key": "korea-seongsu",
            "item_key": "shopping-street",
            "query_text": "韩国 圣水 逛街 小众",
            "license_note": "参考图片",
            "alt_text": "街区逛街参考图片。",
            "metadata_json": {"seed": True},
        },
        {
            "id": SIJIMINFU_IMAGE_ASSET_ID,
            "source_type": "curated",
            "url": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4",
            "thumbnail_url": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=480",
            "source_url": "https://unsplash.com/photos/1517248135467-4c7edcad34c4",
            "source_domain": "unsplash.com",
            "credit": "Product reference image",
            "verified": True,
            "verification_status": "verified",
            "is_ai_generated": False,
            "ai_generated_risk": "low",
            "displayable": True,
            "place_key": "beijing-sijiminfu",
            "item_key": "signature-first-ordering",
            "query_text": "北京 四季民福 烤鸭 点菜",
            "license_note": "参考图片",
            "alt_text": "餐厅点菜参考图片。",
            "metadata_json": {"seed": True},
        },
    ]


def _intents() -> list[dict]:
    return [
        {
            "id": FOOD_INTENT_ID,
            "key": "food_pick_one",
            "name": "Pick one food option",
            "description": "User wants one food recommendation without a long comparison.",
            "examples_json": [{"text": "大同吃什么就选一个"}],
            "is_active": True,
        },
        {
            "id": SHOPPING_INTENT_ID,
            "key": "place_pick_one",
            "name": "Pick one place option",
            "description": "User wants one place or shopping-area recommendation.",
            "examples_json": [{"text": "首尔今天去哪逛"}],
            "is_active": True,
        },
    ]


def _intent_answers() -> list[dict]:
    return [
        {
            "id": FOOD_INTENT_ANSWER_ID,
            "intent_id": FOOD_INTENT_ID,
            "image_asset_id": DATONG_IMAGE_ASSET_ID,
            "answer_text": "选西京刀削面配丸子，稳、快、有地方特色。",
            "intent_key": "food_pick_one",
            "intent_text": "User wants one food option.",
            "answer_title": "刀削面 + 肉丸子",
            "answer_summary": "第一次来大同，刀削面和肉丸子的地方记忆点最强。",
            "constraints_json": {"place": "大同", "item": "刀削面 + 肉丸子"},
            "source_type": "curated_seed",
            "source_ref_id": "seed:datong:knife-cut-noodles",
            "confidence": 0.9,
            "success_count": 0,
            "rejection_count": 0,
            "last_used_at": None,
            "locale": "zh-CN",
            "tags_json": ["food", "datong", "pick-one"],
            "evidence_json": {"source": "curated_seed", "requires_verified_image": True},
            "priority": 10,
            "is_active": True,
        },
        {
            "id": SHOPPING_INTENT_ANSWER_ID,
            "intent_id": SHOPPING_INTENT_ID,
            "image_asset_id": SEONGSU_IMAGE_ASSET_ID,
            "answer_text": "选圣水洞，适合直接逛街、看店、喝咖啡。",
            "intent_key": "place_pick_one",
            "intent_text": "User wants one place or shopping-area recommendation.",
            "answer_title": "去圣水",
            "answer_summary": "圣水比明洞更生活方式，也更适合买小众品牌和美妆。",
            "constraints_json": {"place": "韩国", "avoid": "明洞", "wants": ["小众品牌", "美妆"]},
            "source_type": "curated_seed",
            "source_ref_id": "seed:korea:seongsu",
            "confidence": 0.88,
            "success_count": 0,
            "rejection_count": 0,
            "last_used_at": None,
            "locale": "zh-CN",
            "tags_json": ["place", "seongsu", "pick-one"],
            "evidence_json": {"source": "curated_seed", "requires_verified_image": True},
            "priority": 20,
            "is_active": True,
        },
        {
            "id": SIJIMINFU_INTENT_ANSWER_ID,
            "intent_id": FOOD_INTENT_ID,
            "image_asset_id": SIJIMINFU_IMAGE_ASSET_ID,
            "answer_text": "第一次来四季民福，先吃招牌烤鸭，再配一个清爽菜和甜品。",
            "intent_key": "venue_order.beijing.sijiminfu.signature_first",
            "intent_text": "User is already at Siji Minfu and wants one ordering bundle.",
            "answer_title": "烤鸭 + 清爽配菜 + 甜品",
            "answer_summary": "第一次来四季民福，先吃招牌，口味最稳。",
            "constraints_json": {
                "venue": "四季民福故宫店",
                "people": "默认 2 人",
                "target_type": "ordering_bundle",
            },
            "source_type": "curated_seed",
            "source_ref_id": "seed:beijing:sijiminfu:signature-first-ordering",
            "confidence": 0.9,
            "success_count": 0,
            "rejection_count": 0,
            "last_used_at": None,
            "locale": "zh-CN",
            "tags_json": ["food", "beijing", "sijiminfu", "ordering-bundle"],
            "evidence_json": {"source": "curated_seed", "requires_verified_image": True},
            "priority": 15,
            "is_active": True,
        },
    ]


def main() -> None:
    from app.services.runtime import session_scope

    with session_scope() as session:
        seed_initial_data(session)


if __name__ == "__main__":
    main()
