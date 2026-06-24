from __future__ import annotations

import uuid
from typing import Any

from app.models import IntentAnswer, RecommendationCard
from app.services.intent_answer_metrics import intent_answer_memory_summary


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, *, answers: list[IntentAnswer], cards: list[RecommendationCard]) -> None:
        self.answers = answers
        self.cards = cards

    def scalars(self, statement: Any) -> _ScalarResult:
        entity = statement.column_descriptions[0]["entity"]
        if entity is IntentAnswer:
            return _ScalarResult(self.answers)
        if entity is RecommendationCard:
            return _ScalarResult(self.cards)
        return _ScalarResult([])


def test_intent_answer_memory_summary_tracks_hits_acceptance_and_source_mix() -> None:
    answer_id = uuid.uuid4()
    other_answer_id = uuid.uuid4()
    answers = [
        IntentAnswer(
            id=answer_id,
            intent_id=uuid.uuid4(),
            answer_text="朝阳区热干面就选这家",
            intent_key="area:北京:朝阳区:热干面",
            answer_title="朝阳区热干面，就选这家",
            source_type="curated_seed_pack_v1",
            source_ref_id="seed-1",
            is_active=True,
            confidence=0.8,
            success_count=3,
            rejection_count=1,
        ),
        IntentAnswer(
            id=other_answer_id,
            intent_id=uuid.uuid4(),
            answer_text="五道口韩餐草稿",
            intent_key="area:北京:五道口:韩餐",
            answer_title="五道口韩餐草稿",
            source_type="ops_seed_patch",
            source_ref_id="run-1:case-2",
            is_active=False,
            confidence=0.9,
            success_count=0,
            rejection_count=0,
        ),
    ]
    cards = [
        RecommendationCard(
            id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            source="pytest",
            title="朝阳区热干面，就选这家",
            reason="证据命中 IntentAnswer",
            status="active",
            payload_json={"reference_intent_answer_id": str(answer_id)},
        ),
        RecommendationCard(
            id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            source="pytest",
            title="没有绑定记忆的卡",
            reason="pytest",
            status="active",
            payload_json={},
        ),
    ]

    summary = intent_answer_memory_summary(_FakeSession(answers=answers, cards=cards), top_limit=2)  # type: ignore[arg-type]

    assert summary["total_intent_answer_count"] == 2
    assert summary["active_intent_answer_count"] == 1
    assert summary["draft_intent_answer_count"] == 1
    assert summary["source_type_counts"] == {"curated_seed_pack_v1": 1, "ops_seed_patch": 1}
    assert summary["recommendation_card_count"] == 2
    assert summary["intent_answer_reference_count"] == 1
    assert summary["referenced_intent_answer_count"] == 1
    assert summary["intent_answer_hit_rate"] == 0.5
    assert summary["referenced_answer_coverage_rate"] == 0.5
    assert summary["success_count"] == 3
    assert summary["rejection_count"] == 1
    assert summary["accepted_intent_rate"] == 0.75
    assert summary["average_confidence"] == 0.85
    assert summary["top_answers"][0]["id"] == str(answer_id)
