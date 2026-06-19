from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from .conftest import bootstrap, chat_turn


def test_beijing_chaoyang_hot_dry_noodle_does_not_fallback(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-area-hot-dry-noodle-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="帮我找一下北京市朝阳区最好吃的热干面",
            metadata={"include_debug": True},
        )

        assert "这轮没处理成功" not in str(body.get("assistant_message") or "")
        assert body["response_kind"] != "clarification"
        assert body["location_state"] == "in_area"

        if body["response_kind"] == "recommendation_card":
            card = body["data"]["recommendation_card"]
            assert card["target_type"] == "restaurant"
            assert "朝阳区" in card["title"] or "朝阳区" in card["subtitle"]
            assert "热干面" in card["title"] or "热干面" in card["subtitle"]
        else:
            help_card = body["data"]["help_card"]
            assert help_card["title"] not in {"北京这顿饭，求一个", "这顿饭，求一个"}
            assert "朝阳区" in str(help_card)
            assert "热干面" in str(help_card)

        assert body["debug"]["canonical_query"]
        assert body["debug"]["extracted_slots"]["area"] == "朝阳区"
        assert body["debug"]["extracted_slots"]["food_item"] == "热干面"
        assert body["debug"]["route_priority"] == "area_food"

    run_async(scenario)
