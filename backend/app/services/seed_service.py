from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
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


def seed_initial_data(session: Session) -> None:
    """Seed deterministic curated data used by first-stage local development."""

    _upsert_all(session, ImageAsset, _image_assets())
    _upsert_all(session, Intent, _intents())
    _upsert_all(session, IntentAnswer, _intent_answers())
    session.commit()


def _upsert_all(session: Session, model: type, rows: Iterable[dict]) -> None:
    for row in rows:
        instance = session.scalar(select(model).where(model.id == row["id"]))
        if instance is None:
            session.add(model(**row))
            continue

        for key, value in row.items():
            setattr(instance, key, value)


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
