from __future__ import annotations

import uuid

import pytest

from app.models import RecommendationCard
from app.schemas.cards import CardDetail
from app.services.runtime import serialize_card_detail
from app.tools.errors import ToolValidationError
from app.tools.recommendation import create_recommendation_card


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["reasons", "bullets", "followups", "warning"])
async def test_create_recommendation_card_tool_rejects_legacy_display_fields(field_name: str) -> None:
    with pytest.raises(ToolValidationError):
        legacy_value = "旧 warning 不允许进入 tool" if field_name == "warning" else ["旧版展示字段不允许进入 tool"]
        await create_recommendation_card(
            object(),
            {
                "question_id": str(uuid.uuid4()),
                "item": {"title": "刀削面 + 肉丸子"},
                "decision_factor": {"text": "第一次来大同，地方记忆点最强。"},
                "evidence_ids": ["hit-datong"],
                "confidence": 0.82,
                field_name: legacy_value,
            },
        )


def test_recommendation_card_detail_defaults_to_v2_minimal_contract() -> None:
    card = _legacy_storage_card()

    payload = CardDetail.model_validate(serialize_card_detail(card)).model_dump(mode="json")

    assert payload["item"] == {
        "title": "刀削面 + 肉丸子",
        "subtitle": "大同 · 面食",
        "category": "food",
    }
    assert payload["decision_factor"] == {
        "key": "datong_first_time",
        "text": "第一次来大同，地方记忆点最强。",
    }
    assert payload["image"] is None
    assert payload["evidence_ids"] == ["hit-datong"]
    assert payload["evidence"] == [{"id": "hit-datong", "type": "retrieval_hit"}]
    assert "reasons" not in payload
    assert "bullets" not in payload
    assert "followups" not in payload
    assert "warning" not in payload


def test_legacy_storage_fields_do_not_leak_through_card_response_model() -> None:
    card = _legacy_storage_card()
    raw_payload = serialize_card_detail(card)
    raw_payload.update(
        {
            "reasons": ["旧 reasons"],
            "bullets": ["旧 bullets"],
            "followups": ["旧 followups"],
            "warning": "旧 warning",
        }
    )

    payload = CardDetail.model_validate(raw_payload).model_dump(mode="json")

    assert payload["item"]["title"] == "刀削面 + 肉丸子"
    assert payload["decision_factor"]["text"] == "第一次来大同，地方记忆点最强。"
    assert "reasons" not in payload
    assert "bullets" not in payload
    assert "followups" not in payload
    assert "warning" not in payload


def _legacy_storage_card() -> RecommendationCard:
    return RecommendationCard(
        id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
        tool_call_id=uuid.uuid4(),
        image_asset_id=None,
        image_required=False,
        image_status="missing",
        source="pipi_tool",
        title="刀削面 + 肉丸子",
        subtitle="大同 · 面食",
        reason="第一次来大同，地方记忆点最强。",
        bullets_json=["旧 bullet 不应该出现在 v2 API"],
        warning="旧 warning 不应该出现在 v2 API",
        confidence=0.82,
        status="active",
        payload_json={
            "item": {
                "title": "刀削面 + 肉丸子",
                "subtitle": "大同 · 面食",
                "category": "food",
            },
            "decision_factor": {
                "key": "datong_first_time",
                "text": "第一次来大同，地方记忆点最强。",
            },
            "evidence_ids": ["hit-datong"],
            "reasons": ["旧 reasons 不应该出现在 v2 API"],
            "bullets": ["旧 bullets 不应该出现在 v2 API"],
            "followups": ["旧 followups 不应该出现在 v2 API"],
            "warning": "旧 warning 不应该出现在 v2 API",
        },
    )
