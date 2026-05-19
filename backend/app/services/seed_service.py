from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImageAsset, Intent, IntentAnswer


DATONG_IMAGE_ASSET_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
SEONGSU_IMAGE_ASSET_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
FOOD_INTENT_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
SHOPPING_INTENT_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
FOOD_INTENT_ANSWER_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
SHOPPING_INTENT_ANSWER_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")


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
            "credit": "Curated placeholder, replace before production",
            "verified": True,
            "verification_status": "verified",
            "is_ai_generated": False,
            "place_key": "datong-xijindao",
            "item_key": "knife-cut-noodles-meatball",
            "alt_text": "A bowl of noodles used as a curated food placeholder.",
            "metadata_json": {"seed": True},
        },
        {
            "id": SEONGSU_IMAGE_ASSET_ID,
            "source_type": "curated",
            "url": "https://images.unsplash.com/photo-1517154421773-0529f29ea451",
            "thumbnail_url": "https://images.unsplash.com/photo-1517154421773-0529f29ea451?w=480",
            "source_url": "https://unsplash.com/photos/1517154421773-0529f29ea451",
            "credit": "Curated placeholder, replace before production",
            "verified": True,
            "verification_status": "verified",
            "is_ai_generated": False,
            "place_key": "korea-seongsu",
            "item_key": "shopping-street",
            "alt_text": "A curated shopping street placeholder.",
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
            "locale": "zh-CN",
            "tags_json": ["place", "seongsu", "pick-one"],
            "evidence_json": {"source": "curated_seed", "requires_verified_image": True},
            "priority": 20,
            "is_active": True,
        },
    ]
