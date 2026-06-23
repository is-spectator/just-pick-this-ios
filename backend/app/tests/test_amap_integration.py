from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.models import AgentRun, AmapPoiSearchRun, AmapRouteRun, ToolCall
from app.schemas.tools import BuildAmapUriInput
from app.services.amap_service import AmapService
from app.services.runtime import session_scope


async def _chat(async_client: AsyncClient, message: str, *, include_debug: bool = True) -> dict[str, Any]:
    response = await async_client.post(
        "/v1/chat/turn",
        json={
            "device_uid": f"pytest-amap-{uuid.uuid4()}",
            "message": message,
            "client_context": {"include_debug": include_debug},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_amap_key_missing_keeps_chat_turn_running(
    monkeypatch: pytest.MonkeyPatch,
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "")
    get_settings.cache_clear()

    async def scenario() -> None:
        body = await _chat(async_client, "我到了北京三里屯，有什么好吃的川菜么")
        assert body["conversation_id"]
        assert body["debug"]["amap_disabled"] is True
        assert body["response_kind"] == "recommendation_card"
        assert body["location_state"] == "in_area"
        card = body["data"]["recommendation_card"]
        assert card["target_type"] == "restaurant"
        assert card["place"]["provider"] == "amap"
        assert card["place"]["location"]["coord_type"] == "gcj02"
        assert card["action"]["type"] == "open_amap"
        assert card["action"]["uri"]

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_mock_amap_poi_and_route_create_place_card(
    monkeypatch: pytest.MonkeyPatch,
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "unit-test-amap-key")
    get_settings.cache_clear()

    def fake_get(self: AmapService, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path == "/v3/place/around":
            return {
                "status": "1",
                "pois": [
                    {
                        "id": "B000A8URXB",
                        "name": "三里屯稳稳川菜馆(无)",
                        "type": "餐饮服务;中餐厅;四川菜(川菜)",
                        "typecode": "050102",
                        "address": "三里屯路 19 号",
                        "location": "116.456,39.934",
                        "distance": "680",
                        "tel": "010-12345678",
                    }
                ],
            }
        if path == "/v3/direction/walking":
            return {"status": "1", "route": {"paths": [{"distance": "680", "duration": "540"}]}}
        raise AssertionError(f"unexpected AMap path: {path}")

    monkeypatch.setattr(AmapService, "_get", fake_get)

    async def scenario() -> None:
        body = await _chat(async_client, "我到了北京三里屯，有什么好吃的川菜么")
        assert body["response_kind"] == "recommendation_card"
        assert body["location_state"] == "in_area"
        assert body["ui_events"][0]["type"] == "show_recommendation_card"
        card = body["data"]["recommendation_card"]
        assert card["target_type"] == "restaurant"
        assert card["title"] == "三里屯稳稳川菜馆"
        assert set(card["decision_factor"]) == {"key", "text"}
        assert card["place"]["provider"] == "amap"
        assert card["place"]["poi_id"] == "B000A8URXB"
        assert card["place"]["location"]["coord_type"] == "gcj02"
        assert card["route"]["provider"] == "amap"
        assert card["route"]["distance_meters"] == 680
        assert card["route"]["duration_seconds"] == 540
        assert card["action"]["type"] == "open_amap"
        assert card["action"]["label"] == "高德导航"
        assert card["action"]["uri"]
        assert "unit-test-amap-key" not in json.dumps(body, ensure_ascii=False)

        with session_scope() as session:
            poi_run = session.scalar(select(AmapPoiSearchRun).order_by(AmapPoiSearchRun.created_at.desc()))
            route_run = session.scalar(select(AmapRouteRun).order_by(AmapRouteRun.created_at.desc()))
            assert poi_run is not None
            assert route_run is not None
            assert poi_run.status == "succeeded"
            assert route_run.status == "succeeded"
            assert "key" not in poi_run.request_json
            assert "key" not in route_run.request_json
            assert "unit-test-amap-key" not in json.dumps(poi_run.request_json, ensure_ascii=False)
            assert "unit-test-amap-key" not in json.dumps(route_run.request_json, ensure_ascii=False)
            tool_calls = list(session.scalars(select(ToolCall).order_by(ToolCall.created_at.desc()).limit(5)))
            agent_runs = list(session.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(5)))
            assert "unit-test-amap-key" not in json.dumps(
                [call.arguments_json | (call.result_json or {}) for call in tool_calls],
                ensure_ascii=False,
            )
            assert "unit-test-amap-key" not in json.dumps(
                [run.input_json | (run.output_json or {}) for run in agent_runs],
                ensure_ascii=False,
            )

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_cantonese_profile_prompt_reranks_area_food_candidates(
    monkeypatch: pytest.MonkeyPatch,
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "unit-test-amap-key")
    get_settings.cache_clear()
    seen_keywords: list[str] = []

    def fake_get(self: AmapService, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path == "/v3/place/around":
            seen_keywords.append(str(params.get("keywords")))
            return {
                "status": "1",
                "pois": [
                    {
                        "id": "REJECT_XIANG",
                        "name": "盖码帮·长沙菜馆(望京SOHO店)",
                        "type": "餐饮服务;中餐厅;湖南菜(湘菜)",
                        "typecode": "050107",
                        "address": "望京SOHO",
                        "location": "116.481,39.997",
                        "distance": "80",
                    },
                    {
                        "id": "PREFER_YUE",
                        "name": "粤小馆·顺德菜(望京店)",
                        "type": "餐饮服务;中餐厅;广东菜(粤菜)",
                        "typecode": "050104",
                        "address": "望京SOHO附近",
                        "location": "116.482,39.998",
                        "distance": "620",
                    },
                ],
            }
        if path == "/v3/direction/walking":
            return {"status": "1", "route": {"paths": [{"distance": "620", "duration": "500"}]}}
        raise AssertionError(f"unexpected AMap path: {path}")

    monkeypatch.setattr(AmapService, "_get", fake_get)

    async def scenario() -> None:
        body = await _chat(async_client, "我是广东人，在北京望京soho，给我找个好吃的。")
        assert seen_keywords == ["粤菜"]
        card = body["data"]["recommendation_card"]
        assert card["title"] == "粤小馆·顺德菜(望京店)"
        assert card["place"]["poi_id"] == "PREFER_YUE"
        assert card["subtitle"] == "望京 · 粤菜"
        assert "广东人" in card["decision_factor"]["text"]
        assert "盖码帮" not in json.dumps(card, ensure_ascii=False)

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_chaoyang_soho_cantonese_profile_is_area_food_decision(
    monkeypatch: pytest.MonkeyPatch,
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "unit-test-amap-key")
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    get_settings.cache_clear()
    seen_keywords: list[str] = []

    def fake_get(self: AmapService, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path == "/v3/place/around":
            seen_keywords.append(str(params.get("keywords")))
            return {
                "status": "1",
                "pois": [
                    {
                        "id": "CHAOGUANG_YUE",
                        "name": "朝阳SOHO粤菜小馆",
                        "type": "餐饮服务;中餐厅;广东菜(粤菜)",
                        "typecode": "050104",
                        "address": "朝阳SOHO附近",
                        "location": "116.458,39.922",
                        "distance": "280",
                    }
                ],
            }
        if path == "/v3/direction/walking":
            return {"status": "1", "route": {"paths": [{"distance": "280", "duration": "240"}]}}
        raise AssertionError(f"unexpected AMap path: {path}")

    monkeypatch.setattr(AmapService, "_get", fake_get)

    async def scenario() -> None:
        body = await _chat(async_client, "我是一个广东人，我在北京朝阳 SOHO，有啥好吃的么")
        assert body["response_kind"] == "recommendation_card"
        assert body["location_state"] == "in_area"
        rewrite = body["debug"]["query_rewrite"]
        assert rewrite["original"] == "我是一个广东人，我在北京朝阳 SOHO，有啥好吃的么"
        assert rewrite["rewritten"] == "我是一个广东人，我在北京朝阳SOHO，有啥好吃的么，偏粤菜/清淡口味"
        assert rewrite["changed"] is True
        assert rewrite["entities"]["area"] == "朝阳SOHO"
        assert rewrite["entities"]["cuisine"] == "粤菜"
        assert seen_keywords == ["粤菜"]
        card = body["data"]["recommendation_card"]
        assert card["title"] == "朝阳SOHO粤菜小馆"
        assert card["subtitle"] == "朝阳SOHO · 粤菜"
        assert "广东人" in card["decision_factor"]["text"]

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_chaoyang_hot_dry_noodles_is_area_food_decision(
    monkeypatch: pytest.MonkeyPatch,
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "unit-test-amap-key")
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    get_settings.cache_clear()
    seen_keywords: list[str] = []

    def fake_get(self: AmapService, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path == "/v3/place/around":
            seen_keywords.append(str(params.get("keywords")))
            return {
                "status": "1",
                "pois": [
                    {
                        "id": "CHAoyang_REGANMIAN",
                        "name": "汉口热干面(朝阳店)",
                        "type": "餐饮服务;中餐厅;湖北菜",
                        "typecode": "050100",
                        "address": "朝阳区附近",
                        "location": "116.444,39.922",
                        "distance": "360",
                    }
                ],
            }
        if path == "/v3/direction/walking":
            return {"status": "1", "route": {"paths": [{"distance": "360", "duration": "300"}]}}
        raise AssertionError(f"unexpected AMap path: {path}")

    monkeypatch.setattr(AmapService, "_get", fake_get)

    async def scenario() -> None:
        body = await _chat(async_client, "帮我找一下北京市朝阳区最好吃的热干面")
        assert body["response_kind"] == "recommendation_card"
        assert body["location_state"] == "in_area"
        assert body["ui_events"][0]["type"] == "show_recommendation_card"
        assert seen_keywords == ["热干面"]
        card = body["data"]["recommendation_card"]
        assert card["target_type"] == "restaurant"
        assert card["title"] == "汉口热干面(朝阳店)"
        assert card["subtitle"] == "朝阳区 · 热干面"
        assert "热干面" in card["decision_factor"]["text"]
        assert "clarification" not in body["data"]

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_build_amap_uri_generates_navigation_uri() -> None:
    output = AmapService().build_uri(
        BuildAmapUriInput(
            target_name="三里屯稳稳川菜馆",
            target_lng=116.456,
            target_lat=39.934,
            origin_lng=116.4551,
            origin_lat=39.9337,
            mode="walking",
        )
    )
    assert output.label == "高德导航"
    assert output.uri.startswith("https://uri.amap.com/navigation?")
    assert "to=116.456,39.934" in output.uri
